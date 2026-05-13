"""Registry des stratégies d'attaque par catégorie OWASP."""

from ..enums import AttackCategory
from .base import AttackAttemptPlan, AttackStrategy, TargetContext
from .jailbreak import JailbreakStrategy
from .misinformation import MisinformationStrategy
from .prompt_injection import PromptInjectionStrategy
from .sensitive_info import SensitiveInfoDisclosureStrategy
from .system_prompt_leak import SystemPromptLeakStrategy

STRATEGY_REGISTRY: dict[AttackCategory, type[AttackStrategy]] = {
    AttackCategory.PROMPT_INJECTION: PromptInjectionStrategy,
    AttackCategory.JAILBREAK: JailbreakStrategy,
    AttackCategory.SYSTEM_PROMPT_LEAK: SystemPromptLeakStrategy,
    AttackCategory.SENSITIVE_INFO_DISCLOSURE: SensitiveInfoDisclosureStrategy,
    AttackCategory.MISINFORMATION: MisinformationStrategy,
}

__all__ = [
    "AttackAttemptPlan",
    "AttackStrategy",
    "STRATEGY_REGISTRY",
    "TargetContext",
]
