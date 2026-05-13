"""Registry des stratégies d'attaque par catégorie OWASP."""

from ..enums import AttackCategory
from .base import AttackAttemptPlan, AttackStrategy, TargetContext
from .prompt_injection import PromptInjectionStrategy

STRATEGY_REGISTRY: dict[AttackCategory, type[AttackStrategy]] = {
    AttackCategory.PROMPT_INJECTION: PromptInjectionStrategy,
}

__all__ = [
    "AttackAttemptPlan",
    "AttackStrategy",
    "STRATEGY_REGISTRY",
    "TargetContext",
]
