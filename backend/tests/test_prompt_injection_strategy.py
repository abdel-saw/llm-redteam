"""Tests unitaires de la stratégie Prompt Injection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.app.enums import TargetType
from backend.app.services.llm_client import LLMResponse
from backend.app.strategies.base import TargetContext
from backend.app.strategies.prompt_injection import (
    STATIC_TEMPLATES,
    PromptInjectionStrategy,
)


def _ctx() -> TargetContext:
    return TargetContext(target_type=TargetType.OPENAI_COMPATIBLE)


class TestPromptInjectionStrategy:
    @pytest.mark.asyncio
    async def test_yields_static_templates_only_when_within_static_size(self):
        strategy = PromptInjectionStrategy()
        client = AsyncMock()

        plans = []
        async for plan in strategy.generate_attempts(_ctx(), max_attempts=3, llm_client=client):
            plans.append(plan)

        assert len(plans) == 3
        client.complete.assert_not_called()
        for i, plan in enumerate(plans):
            assert plan.strategy_name == STATIC_TEMPLATES[i][0]
            assert plan.prompt == STATIC_TEMPLATES[i][1]

    @pytest.mark.asyncio
    async def test_adaptive_generation_when_max_exceeds_static_size(self):
        strategy = PromptInjectionStrategy()
        adaptive_payload = {
            "attacks": [
                {"name": "extra_one", "prompt": "Custom attack 1", "goal": "g1"},
                {"name": "extra_two", "prompt": "Custom attack 2", "goal": "g2"},
            ]
        }
        client = AsyncMock()
        client.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps(adaptive_payload),
            raw={},
            provider_used="groq",
            model_used="m",
            latency_ms=1,
        ))

        max_attempts = len(STATIC_TEMPLATES) + 2
        plans = []
        async for plan in strategy.generate_attempts(_ctx(), max_attempts=max_attempts, llm_client=client):
            plans.append(plan)

        assert len(plans) == max_attempts
        client.complete.assert_called_once()
        # Les N premiers plans sont les templates statiques.
        for i, plan in enumerate(plans[: len(STATIC_TEMPLATES)]):
            assert plan.prompt == STATIC_TEMPLATES[i][1]
        # Les 2 suivants viennent de la génération adaptative.
        assert plans[-2].strategy_name == "extra_one"
        assert plans[-2].prompt == "Custom attack 1"
        assert plans[-1].strategy_name == "extra_two"

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_break_static_phase(self):
        strategy = PromptInjectionStrategy()
        client = AsyncMock()
        client.complete = AsyncMock(side_effect=Exception("provider down"))

        max_attempts = len(STATIC_TEMPLATES) + 3
        plans = []
        async for plan in strategy.generate_attempts(_ctx(), max_attempts=max_attempts, llm_client=client):
            plans.append(plan)

        # On garde au moins les statiques même si la phase adaptative casse.
        assert len(plans) == len(STATIC_TEMPLATES)
        client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_malformed_adaptive_items(self):
        strategy = PromptInjectionStrategy()
        adaptive_payload = {
            "attacks": [
                {"name": "ok", "prompt": "Valid attack", "goal": "g"},
                {"name": "missing_prompt"},
                {"prompt": "", "goal": "empty"},
                "not_a_dict",
                {"name": "ok2", "prompt": "Another valid attack", "goal": "g2"},
            ]
        }
        client = AsyncMock()
        client.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps(adaptive_payload),
            raw={}, provider_used="groq", model_used="m", latency_ms=1,
        ))

        plans = []
        async for plan in strategy.generate_attempts(
            _ctx(), max_attempts=len(STATIC_TEMPLATES) + 5, llm_client=client
        ):
            plans.append(plan)

        # 8 statiques + 2 valides parmi 5 candidats malformés.
        assert len(plans) == len(STATIC_TEMPLATES) + 2
        assert plans[-2].prompt == "Valid attack"
        assert plans[-1].prompt == "Another valid attack"
