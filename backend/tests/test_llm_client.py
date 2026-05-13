"""Tests unitaires de la logique retry/fallback de LLMClient.

On utilise respx pour mocker les réponses HTTP de Groq et OpenRouter,
et un monkeypatch sur `asyncio.sleep` pour ne pas vraiment dormir
pendant les retries (et inspecter la valeur effective du delay).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from backend.app.config import Settings
from backend.app.services.llm_client import LLMClient
from backend.app.services.llm_exceptions import LLMUnavailableError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _settings(*, openrouter: bool = False) -> Settings:
    return Settings(
        groq_api_key="fake-groq",
        openrouter_api_key="fake-or" if openrouter else "",
        llm_provider="groq",
        attacker_model="m",
        judge_model="j",
        guard_model="g",
        database_url="sqlite:///:memory:",
    )


def _ok_body(content: str = "hello") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }


@pytest.fixture
def no_real_sleep(monkeypatch):
    """Remplace asyncio.sleep par un AsyncMock pour les tests retry.

    Retourne le mock pour inspection (call args).
    """
    sleep_mock = AsyncMock()
    import backend.app.services.llm_client as mod
    monkeypatch.setattr(mod.asyncio, "sleep", sleep_mock)
    return sleep_mock


class TestLLMClientRetry:
    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_once_on_429_then_succeeds(self, no_real_sleep):
        """Premier 429 sur Groq → sleep → retry sur Groq → 200."""
        route = respx.post(GROQ_URL).mock(side_effect=[
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json=_ok_body("after-retry")),
        ])

        client = LLMClient(_settings())
        result = await client.complete(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "after-retry"
        assert result.provider_used == "groq"
        assert route.call_count == 2
        # Un seul sleep, avec le delay par défaut (pas de Retry-After).
        no_real_sleep.assert_awaited_once_with(2.0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_respects_retry_after_header(self, no_real_sleep):
        """Si le 429 porte Retry-After: 5, on attend 5 s exactement."""
        respx.post(GROQ_URL).mock(side_effect=[
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, json=_ok_body()),
        ])

        client = LLMClient(_settings())
        await client.complete(messages=[{"role": "user", "content": "hi"}])

        no_real_sleep.assert_awaited_once_with(5.0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_caps_at_10_seconds(self, no_real_sleep):
        """Retry-After: 60 → on cap à 10 s pour ne pas geler le scan."""
        respx.post(GROQ_URL).mock(side_effect=[
            httpx.Response(429, headers={"Retry-After": "60"}),
            httpx.Response(200, json=_ok_body()),
        ])

        client = LLMClient(_settings())
        await client.complete(messages=[{"role": "user", "content": "hi"}])

        no_real_sleep.assert_awaited_once_with(10.0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_then_falls_back_to_other_provider_if_still_429(
        self, no_real_sleep
    ):
        """Groq: 429 puis 429 (retry échoue) → bascule sur OpenRouter."""
        groq = respx.post(GROQ_URL).mock(side_effect=[
            httpx.Response(429),
            httpx.Response(429),
        ])
        openrouter = respx.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_ok_body("from-or"))
        )

        client = LLMClient(_settings(openrouter=True))
        result = await client.complete(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "from-or"
        assert result.provider_used == "openrouter"
        assert groq.call_count == 2          # 1 essai + 1 retry
        assert openrouter.call_count == 1    # fallback
        # Sleep une fois (retry sur Groq) — pas de retry sur le fallback.
        assert no_real_sleep.await_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_retry_on_other_errors(self, no_real_sleep):
        """500 sur Groq → fallback direct sur OpenRouter, sans retry/sleep."""
        groq = respx.post(GROQ_URL).mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        openrouter = respx.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_ok_body("from-or"))
        )

        client = LLMClient(_settings(openrouter=True))
        result = await client.complete(messages=[{"role": "user", "content": "hi"}])

        assert result.provider_used == "openrouter"
        assert groq.call_count == 1
        assert openrouter.call_count == 1
        no_real_sleep.assert_not_awaited()

    @respx.mock
    @pytest.mark.asyncio
    async def test_all_providers_429_after_retry_raises(self, no_real_sleep):
        """Tous les providers répondent 429 même après retry → LLMUnavailable."""
        respx.post(GROQ_URL).mock(return_value=httpx.Response(429))
        respx.post(OPENROUTER_URL).mock(return_value=httpx.Response(429))

        client = LLMClient(_settings(openrouter=True))
        with pytest.raises(LLMUnavailableError):
            await client.complete(messages=[{"role": "user", "content": "hi"}])

        # 2 sleep : un par provider (chaque provider tente son retry).
        assert no_real_sleep.await_count == 2
