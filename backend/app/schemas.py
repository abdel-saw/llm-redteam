"""DTO Pydantic v2 — frontière de l'API.

Conversions JSON <-> dict / list pour les champs sérialisés en DB :
- `Target.headers_json` <-> `headers: dict[str, str] | None`
- `Scan.selected_categories_json` <-> `selected_categories: list[AttackCategory]`

Ces conversions s'appuient sur les propriétés Python des modèles ORM (cf.
`models.py`), de sorte que `model_config = ConfigDict(from_attributes=True)`
suffit pour lire depuis un objet SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import AttackCategory, JudgmentVerdict, ScanStatus, Severity, TargetType


# ----------------------------- Targets ---------------------------------------


class TargetBase(BaseModel):
    # `protected_namespaces=()` désactive le warning Pydantic v2 sur le champ
    # `model_name` (préfixe `model_` réservé). On ne définit pas d'attribut
    # interne `model_*`, donc aucun risque de collision.
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=255)
    target_type: TargetType
    endpoint_url: str = Field(min_length=1, max_length=1024)
    headers: Optional[dict[str, str]] = None
    request_template: Optional[str] = None
    response_path: Optional[str] = None
    model_name: Optional[str] = None


class TargetCreate(TargetBase):
    @model_validator(mode="after")
    def _check_conditional_fields(self) -> "TargetCreate":
        if self.target_type == TargetType.JSON_CUSTOM:
            missing = [
                f for f, v in (("request_template", self.request_template),
                               ("response_path", self.response_path)) if not v
            ]
            if missing:
                raise ValueError(
                    f"target_type=json_custom requires: {', '.join(missing)}"
                )
        if self.target_type == TargetType.OPENAI_COMPATIBLE:
            if not self.model_name:
                raise ValueError("target_type=openai_compatible requires: model_name")
        return self


class TargetRead(TargetBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class TargetTestRequest(BaseModel):
    """Body optionnel pour POST /api/targets/{id}/test."""

    prompt: Optional[str] = Field(
        default=None,
        description="Override du prompt de test. Si absent, ping par défaut.",
    )


class ConnectionTestResult(BaseModel):
    ok: bool
    status_code: Optional[int] = None
    sample_response: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


class TargetTestResponse(ConnectionTestResult):
    """Alias sémantique exposé par la route /test."""


# ----------------------------- Scans -----------------------------------------


class ScanCreate(BaseModel):
    target_id: int
    selected_categories: list[AttackCategory] = Field(min_length=1)
    max_attempts_per_category: int = Field(default=5, ge=1, le=50)


class ScanRead(BaseModel):
    id: int
    target_id: int
    status: ScanStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    selected_categories: list[AttackCategory]
    max_attempts_per_category: int
    total_attempts: int
    successful_attacks: int
    robustness_score: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScanSummary(BaseModel):
    """Vue allégée pour listings (sans les détails des tentatives)."""

    id: int
    target_id: int
    status: ScanStatus
    created_at: datetime
    total_attempts: int
    successful_attacks: int
    robustness_score: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# ----------------------------- Attempts --------------------------------------


class AttackAttemptRead(BaseModel):
    id: int
    scan_id: int
    category: AttackCategory
    strategy_name: str
    attack_prompt: str
    target_response: Optional[str] = None
    judgment: Optional[JudgmentVerdict] = None
    judgment_reasoning: Optional[str] = None
    severity: Optional[Severity] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
