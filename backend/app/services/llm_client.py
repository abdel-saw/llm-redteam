"""Client LLM unifié pour les appels internes (attaquant + juge).

Supporte Groq et OpenRouter via httpx direct. En cas d'échec du provider
principal, bascule automatiquement sur l'autre. Le format de requête est
OpenAI-compatible côté `messages` et `response_format`.

Retry policy sur 429 : un seul retry est tenté sur le même provider,
après avoir respecté le header `Retry-After` (cappé à 10 s pour ne pas
geler un scan si l'API renvoie une valeur fantaisiste). Si le retry
échoue encore, on bascule sur le provider suivant comme avant.

`get_llm_client()` retourne un singleton lazy-initialisé.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import Settings, get_settings
from .llm_exceptions import LLMError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError

logger = logging.getLogger(__name__)

PROVIDER_ENDPOINTS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_RETRY_AFTER_S = 2.0
MAX_RETRY_AFTER_S = 10.0


@dataclass
class LLMResponse:
    content: str
    raw: dict
    provider_used: str
    model_used: str
    latency_ms: int
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        chosen_model = model or self.settings.attacker_model
        primary = self.settings.llm_provider
        ordered = [primary] + [p for p in PROVIDER_ENDPOINTS if p != primary]

        last_error: Optional[Exception] = None
        for idx, provider in enumerate(ordered):
            api_key = self._api_key(provider)
            if not api_key:
                logger.info("Skipping %s (no API key configured)", provider)
                continue
            try:
                return await self._call_with_retry(
                    provider, api_key, chosen_model, messages,
                    temperature, max_tokens, response_format,
                )
            except (httpx.HTTPError, LLMError) as exc:
                last_error = exc
                if idx < len(ordered) - 1:
                    logger.warning(
                        "%s call failed (%s) — trying next provider", provider, exc
                    )
                else:
                    logger.error("All providers exhausted. Last error: %s", exc)

        raise LLMUnavailableError(
            f"All providers exhausted. Last error: {last_error}"
        )

    async def _call_with_retry(
        self,
        provider: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        """Appelle un provider avec UN seul retry sur 429.

        Le retry respecte le header `Retry-After` (cap MAX_RETRY_AFTER_S).
        Sur toute autre erreur, on remonte immédiatement à l'appelant pour
        que le fallback provider prenne le relais sans temporisation.
        """
        try:
            return await self._call_provider(
                provider, api_key, model, messages,
                temperature, max_tokens, response_format,
            )
        except LLMRateLimitError as first_429:
            delay = min(
                first_429.retry_after if first_429.retry_after is not None
                else DEFAULT_RETRY_AFTER_S,
                MAX_RETRY_AFTER_S,
            )
            logger.warning(
                "Rate limit hit on %s, retrying in %.1fs", provider, delay
            )
            t_retry_start = time.perf_counter()
            await asyncio.sleep(delay)
            result = await self._call_provider(
                provider, api_key, model, messages,
                temperature, max_tokens, response_format,
            )
            # Le délai d'attente fait partie de la latence perçue par
            # l'appelant — on cumule sleep + 2e appel, et on log un
            # breakdown explicite pour l'audit.
            total_ms = int((time.perf_counter() - t_retry_start) * 1000) + result.latency_ms
            logger.info(
                "[provider=%s] 429 then 200 in %dms (retry delay %dms)",
                provider, total_ms, int(delay * 1000),
            )
            result.latency_ms = total_ms
            return result

    def _api_key(self, provider: str) -> Optional[str]:
        if provider == "groq":
            return self.settings.groq_api_key or None
        if provider == "openrouter":
            return self.settings.openrouter_api_key or None
        return None

    async def _call_provider(
        self,
        provider: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        """Un seul appel HTTP vers le provider — pas de retry interne."""
        url = PROVIDER_ENDPOINTS[provider]
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/abdel-saw/llm-redteam"
            headers["X-Title"] = "Red-Agent-S"

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"{provider} timed out after {DEFAULT_TIMEOUT_S}s") from exc

        latency_ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise LLMRateLimitError(
                f"{provider} rate limited (429)", retry_after=retry_after
            )
        resp.raise_for_status()

        try:
            raw = resp.json()
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailableError(f"Malformed response from {provider}: {exc}") from exc

        usage = raw.get("usage") or {}
        logger.info(
            "LLM call OK: provider=%s model=%s in=%s out=%s latency=%dms",
            provider, model, usage.get("prompt_tokens"),
            usage.get("completion_tokens"), latency_ms,
        )
        return LLMResponse(
            content=content,
            raw=raw,
            provider_used=provider,
            model_used=model,
            latency_ms=latency_ms,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )


def _parse_retry_after(header: Optional[str]) -> Optional[float]:
    """Parse le header `Retry-After`. RFC 7231 : un entier de secondes, ou
    une date HTTP. Pour le MVP on supporte uniquement la forme entière —
    si la valeur est invalide ou absente, retourne None et l'appelant
    utilise `DEFAULT_RETRY_AFTER_S`."""
    if header is None:
        return None
    try:
        return float(header.strip())
    except (ValueError, AttributeError):
        return None


_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Singleton lazy. Réutilise les settings courants."""
    global _instance
    if _instance is None:
        _instance = LLMClient(get_settings())
    return _instance


def reset_llm_client() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _instance
    _instance = None
