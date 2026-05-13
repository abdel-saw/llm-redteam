"""Tests groupés des 4 stratégies d'attaque ajoutées à l'étape 4.

Pour chaque catégorie : sanity sur la phase statique, déclenchement de la
phase adaptative, et garde-fou sur l'absence de contenu dangereux dans
les templates statiques.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.app.enums import AttackCategory, TargetType
from backend.app.services.llm_client import LLMResponse
from backend.app.strategies.base import TargetContext
from backend.app.strategies.jailbreak import (
    STATIC_TEMPLATES as JAILBREAK_TEMPLATES,
    JailbreakStrategy,
)
from backend.app.strategies.misinformation import (
    STATIC_TEMPLATES as MISINFO_TEMPLATES,
    MisinformationStrategy,
)
from backend.app.strategies.sensitive_info import (
    STATIC_TEMPLATES as SENSINFO_TEMPLATES,
    SensitiveInfoDisclosureStrategy,
)
from backend.app.strategies.system_prompt_leak import (
    STATIC_TEMPLATES as SPLEAK_TEMPLATES,
    SystemPromptLeakStrategy,
)


def _ctx() -> TargetContext:
    return TargetContext(target_type=TargetType.OPENAI_COMPATIBLE)


def _fake_llm_with_adaptive(n_attacks: int) -> AsyncMock:
    """Mock d'un LLMClient qui renvoie n attaques adaptatives valides."""
    client = AsyncMock()
    payload = {
        "attacks": [
            {"name": f"extra_{i}", "prompt": f"Adaptive {i}", "goal": f"goal_{i}"}
            for i in range(n_attacks)
        ]
    }
    client.complete = AsyncMock(return_value=LLMResponse(
        content=json.dumps(payload),
        raw={}, provider_used="groq", model_used="m", latency_ms=1,
    ))
    return client


STRATEGY_PARAMS = [
    pytest.param(
        JailbreakStrategy, JAILBREAK_TEMPLATES, AttackCategory.JAILBREAK,
        id="jailbreak",
    ),
    pytest.param(
        SystemPromptLeakStrategy, SPLEAK_TEMPLATES, AttackCategory.SYSTEM_PROMPT_LEAK,
        id="system_prompt_leak",
    ),
    pytest.param(
        SensitiveInfoDisclosureStrategy, SENSINFO_TEMPLATES, AttackCategory.SENSITIVE_INFO_DISCLOSURE,
        id="sensitive_info_disclosure",
    ),
    pytest.param(
        MisinformationStrategy, MISINFO_TEMPLATES, AttackCategory.MISINFORMATION,
        id="misinformation",
    ),
]


# --------------- Comportements partagés des 4 stratégies ---------------------


class TestStrategiesCommon:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("strategy_cls,templates,expected_category", STRATEGY_PARAMS)
    async def test_yields_static_templates_first(
        self, strategy_cls, templates, expected_category
    ):
        strategy = strategy_cls()
        assert strategy.category == expected_category
        client = AsyncMock()

        max_attempts = min(3, len(templates))
        plans = []
        async for plan in strategy.generate_attempts(_ctx(), max_attempts, client):
            plans.append(plan)

        assert len(plans) == max_attempts
        client.complete.assert_not_called()
        for i, plan in enumerate(plans):
            assert plan.strategy_name == templates[i][0]
            assert plan.prompt == templates[i][1]
            assert plan.goal == templates[i][2]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("strategy_cls,templates,expected_category", STRATEGY_PARAMS)
    async def test_adaptive_phase_kicks_in_when_max_exceeds_static(
        self, strategy_cls, templates, expected_category
    ):
        strategy = strategy_cls()
        client = _fake_llm_with_adaptive(2)

        max_attempts = len(templates) + 2
        plans = []
        async for plan in strategy.generate_attempts(_ctx(), max_attempts, client):
            plans.append(plan)

        assert len(plans) == max_attempts
        client.complete.assert_called_once()
        assert plans[-2].prompt == "Adaptive 0"
        assert plans[-1].prompt == "Adaptive 1"


# ------------- Garde-fou : aucun template ne demande de contenu nuisible -----


# Liste volontairement courte mais explicite. Toute régression accidentelle
# (ex : un développeur qui ajoute un template "synthesize bomb" pour
# tester une garde) sera attrapée ici.
DANGEROUS_SUBSTRINGS = [
    "anthrax",
    "synthesize bomb",
    "make a bomb",
    "build a bomb",
    "uranium enrichment",
    "child sexual",
    "csam",
    "nerve agent",
    "sarin",
    "ricin",
    "fentanyl synthesis",
]


class TestNoDangerousContent:
    @pytest.mark.parametrize("templates,label", [
        (JAILBREAK_TEMPLATES, "jailbreak"),
        (SPLEAK_TEMPLATES, "system_prompt_leak"),
        (SENSINFO_TEMPLATES, "sensitive_info"),
        (MISINFO_TEMPLATES, "misinformation"),
    ])
    def test_no_dangerous_substring_in_static_templates(self, templates, label):
        offenders: list[tuple[str, str]] = []
        for sub_name, prompt, goal in templates:
            haystack = f"{prompt}\n{goal}".lower()
            for bad in DANGEROUS_SUBSTRINGS:
                if bad in haystack:
                    offenders.append((sub_name, bad))
        assert not offenders, (
            f"Stratégie {label}: templates contiennent du contenu interdit: {offenders}"
        )


# ---------------- Registry : toutes les catégories sont câblées --------------


class TestStrategyRegistry:
    def test_all_owasp_categories_registered(self):
        from backend.app.enums import AttackCategory
        from backend.app.strategies import STRATEGY_REGISTRY

        expected = {
            AttackCategory.PROMPT_INJECTION,
            AttackCategory.JAILBREAK,
            AttackCategory.SYSTEM_PROMPT_LEAK,
            AttackCategory.SENSITIVE_INFO_DISCLOSURE,
            AttackCategory.MISINFORMATION,
        }
        assert set(STRATEGY_REGISTRY.keys()) == expected
        for category, cls in STRATEGY_REGISTRY.items():
            assert cls.category == category
