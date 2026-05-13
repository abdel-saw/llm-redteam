"""Adaptateurs de cibles LLM (pattern Adapter).

Trois implémentations pour les trois `TargetType` :
- `TextAdapter` : POST texte brut, réponse renvoyée telle quelle.
- `JsonCustomAdapter` : sérialisation par template `{{prompt}}` + extraction
  JSONPath de la réponse.
- `OpenAICompatibleAdapter` : format `/chat/completions` standard.

La factory `get_adapter` retourne l'implémentation adaptée à `target.target_type`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Optional, Union

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from ..enums import TargetType
from ..models import Target
from ..schemas import ConnectionTestResult

DEFAULT_PING_PROMPT = "Hello, can you respond with a short greeting?"
DEFAULT_TIMEOUT_S = 30.0
_SAMPLE_RESPONSE_MAX = 300


@dataclass
class AdapterResponse:
    response_text: str
    raw_response: Union[dict, list, str]
    latency_ms: int
    status_code: int


class TargetAdapter(ABC):
    def __init__(self, target: Target, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.target = target
        self.timeout = timeout
        self.headers = self._parse_headers(target.headers_json)

    @staticmethod
    def _parse_headers(headers_json: Optional[str]) -> dict[str, str]:
        if not headers_json:
            return {}
        try:
            value = json.loads(headers_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items()}

    @abstractmethod
    async def send(self, prompt: str) -> AdapterResponse:
        """Envoie le `prompt` à la cible et renvoie la réponse normalisée."""

    async def test_connection(self, prompt: Optional[str] = None) -> ConnectionTestResult:
        """Ping de la cible. Renvoie un résultat structuré, ne lève jamais."""
        ping = prompt if prompt is not None else DEFAULT_PING_PROMPT
        start = perf_counter()
        try:
            result = await self.send(ping)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else ""
            return ConnectionTestResult(
                ok=False,
                status_code=exc.response.status_code if exc.response is not None else None,
                sample_response=body[:_SAMPLE_RESPONSE_MAX] or None,
                error=f"HTTP {exc.response.status_code if exc.response is not None else '?'}",
                latency_ms=int((perf_counter() - start) * 1000),
            )
        except httpx.HTTPError as exc:
            return ConnectionTestResult(
                ok=False,
                status_code=None,
                sample_response=None,
                error=f"Network error: {exc!s}",
                latency_ms=int((perf_counter() - start) * 1000),
            )
        except (ValueError, KeyError) as exc:
            return ConnectionTestResult(
                ok=False,
                status_code=None,
                sample_response=None,
                error=f"Adapter error: {exc!s}",
                latency_ms=int((perf_counter() - start) * 1000),
            )

        return ConnectionTestResult(
            ok=True,
            status_code=result.status_code,
            sample_response=(result.response_text or "")[:_SAMPLE_RESPONSE_MAX] or None,
            error=None,
            latency_ms=result.latency_ms,
        )


class TextAdapter(TargetAdapter):
    """POST texte brut → réponse texte brut."""

    async def send(self, prompt: str) -> AdapterResponse:
        headers = {"Content-Type": "text/plain; charset=utf-8", **self.headers}
        start = perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.target.endpoint_url, content=prompt.encode("utf-8"), headers=headers
            )
        latency_ms = int((perf_counter() - start) * 1000)
        resp.raise_for_status()
        text = resp.text
        return AdapterResponse(
            response_text=text,
            raw_response=text,
            latency_ms=latency_ms,
            status_code=resp.status_code,
        )


class JsonCustomAdapter(TargetAdapter):
    """Template JSON paramétrable.

    Le template doit utiliser `{{prompt}}` non quoté (la substitution insère
    une valeur JSON déjà quotée via `json.dumps`). Exemple valide :

        {"input": {{prompt}}, "metadata": {"v": 1}}
    """

    async def send(self, prompt: str) -> AdapterResponse:
        if not self.target.request_template:
            raise ValueError("json_custom requires request_template")
        if not self.target.response_path:
            raise ValueError("json_custom requires response_path")

        substituted = self.target.request_template.replace(
            "{{prompt}}", json.dumps(prompt)
        )
        try:
            body = json.loads(substituted)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON after template substitution: {exc}") from exc

        headers = {"Content-Type": "application/json", **self.headers}
        start = perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.target.endpoint_url, json=body, headers=headers)
        latency_ms = int((perf_counter() - start) * 1000)
        resp.raise_for_status()

        try:
            raw: Any = resp.json()
        except ValueError as exc:
            raise ValueError(f"Target returned non-JSON response: {exc}") from exc

        extracted = self._extract(raw, self.target.response_path)
        return AdapterResponse(
            response_text=extracted,
            raw_response=raw,
            latency_ms=latency_ms,
            status_code=resp.status_code,
        )

    @staticmethod
    def _extract(payload: Any, path: str) -> str:
        try:
            expr = jsonpath_parse(path)
        except Exception as exc:  # noqa: BLE001 - jsonpath-ng raises bare Exception
            raise ValueError(f"Invalid JSONPath '{path}': {exc}") from exc
        matches = [m.value for m in expr.find(payload)]
        if not matches:
            return json.dumps(payload, ensure_ascii=False)
        first = matches[0]
        return first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)


class OpenAICompatibleAdapter(TargetAdapter):
    """Format OpenAI `chat/completions` (Groq, OpenRouter, vLLM, etc.)."""

    async def send(self, prompt: str) -> AdapterResponse:
        if not self.target.model_name:
            raise ValueError("openai_compatible requires model_name")

        url = self._completions_url(self.target.endpoint_url)
        body = {
            "model": self.target.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        headers = {"Content-Type": "application/json", **self.headers}

        start = perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
        latency_ms = int((perf_counter() - start) * 1000)
        resp.raise_for_status()

        try:
            raw = resp.json()
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"Unexpected OpenAI response shape: {exc}") from exc

        return AdapterResponse(
            response_text=content,
            raw_response=raw,
            latency_ms=latency_ms,
            status_code=resp.status_code,
        )

    @staticmethod
    def _completions_url(base: str) -> str:
        url = base.rstrip("/")
        return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


_ADAPTERS: dict[TargetType, type[TargetAdapter]] = {
    TargetType.TEXT: TextAdapter,
    TargetType.JSON_CUSTOM: JsonCustomAdapter,
    TargetType.OPENAI_COMPATIBLE: OpenAICompatibleAdapter,
}


def get_adapter(target: Target, timeout: float = DEFAULT_TIMEOUT_S) -> TargetAdapter:
    """Factory : sélectionne l'adapter selon `target.target_type`."""
    tt = target.target_type
    if not isinstance(tt, TargetType):
        tt = TargetType(tt)
    try:
        cls = _ADAPTERS[tt]
    except KeyError as exc:
        raise ValueError(f"Unsupported target_type: {tt}") from exc
    return cls(target, timeout=timeout)
