"""Énumérations centralisées du domaine Red-Agent-S.

Toutes les énumérations héritent de `(str, Enum)` pour que :
- les valeurs soient sérialisables JSON sans converter custom ;
- la comparaison avec une chaîne brute fonctionne (`status == "running"`) ;
- la persistance via SQLAlchemy `Enum(values_callable=...)` stocke la `value`
  lisible plutôt que le `name` Python.
"""

from enum import Enum


class TargetType(str, Enum):
    TEXT = "text"
    JSON_CUSTOM = "json_custom"
    OPENAI_COMPATIBLE = "openai_compatible"


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class JudgmentVerdict(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    ERROR = "error"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AttackCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"
    SENSITIVE_INFO_DISCLOSURE = "sensitive_info_disclosure"
    MISINFORMATION = "misinformation"
