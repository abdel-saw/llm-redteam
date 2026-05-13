"""Client LLM unifié pour les appels internes (attaquant + juge).

Supporte Groq et OpenRouter via httpx direct. En cas d'échec du provider
principal, bascule automatiquement sur l'autre. Le format de requête est
OpenAI-compatible côté `messages` et `response_format`.

`get_llm_client()` retourne un singleton lazy-initialisé.
"""

from __future__ import annotations

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
                return await self._call_provider(
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
            headers["X-Title"] = "LLM-RT"

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"{provider} timed out after {DEFAULT_TIMEOUT_S}s") from exc

        latency_ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code == 429:
            raise LLMRateLimitError(f"{provider} rate limited (429)")
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
