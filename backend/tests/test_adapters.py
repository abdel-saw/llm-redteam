"""Tests unitaires des adaptateurs cibles (mocking httpx via respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.app.enums import TargetType
from backend.app.models import Target
from backend.app.services.target_adapter import (
    JsonCustomAdapter,
    OpenAICompatibleAdapter,
    TextAdapter,
    get_adapter,
)


def make_target(target_type: TargetType, **kwargs) -> Target:
    """Construit un objet ORM `Target` non persisté (utilisable hors session)."""
    defaults = dict(
        id=1,
        name="t",
        endpoint_url="https://api.example.com/x",
        headers_json=None,
        request_template=None,
        response_path=None,
        model_name=None,
    )
    defaults.update(kwargs)
    return Target(target_type=target_type, **defaults)


# ----------------------------- TextAdapter -----------------------------------


class TestTextAdapter:
    @pytest.mark.asyncio
    @respx.mock
    async def test_posts_raw_text_body(self):
        target = make_target(TargetType.TEXT, endpoint_url="https://api.example.com/chat")
        route = respx.post("https://api.example.com/chat").mock(
            return_value=httpx.Response(200, text="hello back")
        )

        adapter = TextAdapter(target)
        result = await adapter.send("ping")

        assert route.called
        assert route.calls.last.request.content == b"ping"
        assert result.response_text == "hello back"
        assert result.status_code == 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_headers_are_merged(self):
        target = make_target(
            TargetType.TEXT,
            endpoint_url="https://api.example.com/chat",
            headers_json=json.dumps({"X-Api-Key": "secret"}),
        )
        respx.post("https://api.example.com/chat").mock(
            return_value=httpx.Response(200, text="ok")
        )

        await TextAdapter(target).send("ping")

        last = respx.calls.last.request
        assert last.headers.get("x-api-key") == "secret"
        assert last.headers.get("content-type", "").startswith("text/plain")

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_propagates(self):
        target = make_target(TargetType.TEXT, endpoint_url="https://api.example.com/chat")
        respx.post("https://api.example.com/chat").mock(
            return_value=httpx.Response(500, text="boom")
        )

        with pytest.raises(httpx.HTTPStatusError):
            await TextAdapter(target).send("ping")


# --------------------------- JsonCustomAdapter -------------------------------


class TestJsonCustomAdapter:
    @pytest.mark.asyncio
    @respx.mock
    async def test_substitutes_template_with_json_escaped_prompt(self):
        target = make_target(
            TargetType.JSON_CUSTOM,
            endpoint_url="https://api.example.com/x",
            request_template='{"input": {{prompt}}, "version": 2}',
            response_path="$.data.text",
        )
        respx.post("https://api.example.com/x").mock(
            return_value=httpx.Response(200, json={"data": {"text": "hi there"}})
        )

        # Le prompt contient des guillemets → json.dumps doit les échapper.
        result = await JsonCustomAdapter(target).send('Hello "world"')

        sent = json.loads(respx.calls.last.request.content)
        assert sent == {"input": 'Hello "world"', "version": 2}
        assert result.response_text == "hi there"

    @pytest.mark.asyncio
    @respx.mock
    async def test_extracts_first_match_when_multiple(self):
        target = make_target(
            TargetType.JSON_CUSTOM,
            request_template='{"q": {{prompt}}}',
            response_path="$.items[*].text",
        )
        respx.post("https://api.example.com/x").mock(
            return_value=httpx.Response(
                200, json={"items": [{"text": "first"}, {"text": "second"}]}
            )
        )

        result = await JsonCustomAdapter(target).send("hi")

        assert result.response_text == "first"

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_raw_when_path_does_not_match(self):
        raw = {"other": "value"}
        target = make_target(
            TargetType.JSON_CUSTOM,
            request_template='{"q": {{prompt}}}',
            response_path="$.missing",
        )
        respx.post("https://api.example.com/x").mock(
            return_value=httpx.Response(200, json=raw)
        )

        result = await JsonCustomAdapter(target).send("hi")

        assert json.loads(result.response_text) == raw

    @pytest.mark.asyncio
    async def test_raises_when_template_missing(self):
        target = make_target(TargetType.JSON_CUSTOM, response_path="$.r")
        with pytest.raises(ValueError, match="request_template"):
            await JsonCustomAdapter(target).send("hi")


# ------------------------- OpenAICompatibleAdapter ---------------------------


class TestOpenAICompatibleAdapter:
    @pytest.mark.asyncio
    @respx.mock
    async def test_builds_chat_completions_request(self):
        target = make_target(
            TargetType.OPENAI_COMPATIBLE,
            endpoint_url="https://api.groq.com/openai/v1",
            model_name="llama-3.3-70b-versatile",
            headers_json=json.dumps({"Authorization": "Bearer fake"}),
        )
        respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Hello, friend!"}}]},
            )
        )

        result = await OpenAICompatibleAdapter(target).send("Hi")

        last = respx.calls.last.request
        body = json.loads(last.content)
        assert body["model"] == "llama-3.3-70b-versatile"
        assert body["messages"] == [{"role": "user", "content": "Hi"}]
        assert "temperature" in body
        assert last.headers.get("authorization") == "Bearer fake"
        assert result.response_text == "Hello, friend!"

    @pytest.mark.asyncio
    @respx.mock
    async def test_endpoint_already_complete_is_kept_as_is(self):
        target = make_target(
            TargetType.OPENAI_COMPATIBLE,
            endpoint_url="https://api.openai.com/v1/chat/completions",
            model_name="gpt-4o-mini",
        )
        route = respx.post(
            "https://api.openai.com/v1/chat/completions"
        ).mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}
            )
        )

        await OpenAICompatibleAdapter(target).send("hi")

        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_malformed_response(self):
        target = make_target(
            TargetType.OPENAI_COMPATIBLE,
            endpoint_url="https://api.example.com/v1",
            model_name="x",
        )
        respx.post("https://api.example.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"unexpected": "shape"})
        )

        with pytest.raises(ValueError, match="Unexpected OpenAI response shape"):
            await OpenAICompatibleAdapter(target).send("hi")


# ------------------------------- Factory -------------------------------------


class TestFactory:
    def test_returns_correct_adapter_per_type(self):
        t1 = make_target(TargetType.TEXT)
        t2 = make_target(
            TargetType.JSON_CUSTOM,
            request_template='{"p": {{prompt}}}',
            response_path="$.r",
        )
        t3 = make_target(TargetType.OPENAI_COMPATIBLE, model_name="x")

        assert isinstance(get_adapter(t1), TextAdapter)
        assert isinstance(get_adapter(t2), JsonCustomAdapter)
        assert isinstance(get_adapter(t3), OpenAICompatibleAdapter)

    def test_normalizes_string_target_type(self):
        target = make_target(TargetType.TEXT)
        # Simule l'état après hydratation depuis la DB où target_type peut
        # être renvoyé comme chaîne brute par certains backends.
        target.target_type = "text"  # type: ignore[assignment]
        assert isinstance(get_adapter(target), TextAdapter)
