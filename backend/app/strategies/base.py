"""Pattern Strategy — base abstraite pour les familles d'attaque."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..enums import AttackCategory, TargetType

if TYPE_CHECKING:
    from ..services.llm_client import LLMClient


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
