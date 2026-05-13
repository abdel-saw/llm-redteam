"""Pattern Strategy — base abstraite pour les familles d'attaque."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..enums import AttackCategory, TargetType

if TYPE_CHECKING:
    from ..services.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class AttackAttemptPlan:
    """Une tentative planifiée par la stratégie, prête à être envoyée."""

    strategy_name: str
    prompt: str
    goal: str


@dataclass
class TargetContext:
    """Informations connues sur la cible, partagées avec la stratégie.

    `suspected_role` est un placeholder pour le MVP — sera affiné via un
    profilage automatique de la cible dans une itération future.
    """

    target_type: TargetType
    suspected_role: str = "general assistant"


class AttackStrategy(ABC):
    category: AttackCategory
    name: str
    description: str

    @abstractmethod
    def generate_attempts(
        self,
        target_context: TargetContext,
        max_attempts: int,
        llm_client: "LLMClient",
    ) -> AsyncIterator[AttackAttemptPlan]:
        """Génère un flux asynchrone de plans d'attaque (jusqu'à `max_attempts`)."""


async def adaptive_variants_from_llm(
    llm_client: "LLMClient",
    system_prompt: str,
    user_prompt: str,
    n: int,
) -> list[dict[str, Any]]:
    """Helper partagé : demande au LLM `n` variantes au format JSON strict.

    Renvoie une liste de dicts (au plus `n`) filtrée des entrées non-dict.
    Renvoie `[]` si l'appel échoue ou si la réponse est malformée — la
    stratégie appelante reste fonctionnelle (phase statique conservée).
    """
    if n <= 0:
        return []
    try:
        resp = await llm_client.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.content)
        attacks = data.get("attacks", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001 - aucune raison de casser le scan
        logger.warning("Adaptive attack generation failed: %s", exc)
        return []
    return [a for a in attacks if isinstance(a, dict)][:n]
