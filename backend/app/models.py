"""Modèles ORM SQLAlchemy 2.0.

Les colonnes JSON sérialisées (`headers_json`, `selected_categories_json`) sont
exposées sous forme désérialisée via des propriétés Python afin que les schémas
Pydantic puissent les lire directement avec `from_attributes=True`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base
from .enums import AttackCategory, JudgmentVerdict, ScanStatus, Severity, TargetType


def _enum_values(enum_cls):
    """Liste des valeurs lisibles d'une Enum — utilisé par SAEnum."""
    return [member.value for member in enum_cls]


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[TargetType] = mapped_column(
        SAEnum(TargetType, values_callable=_enum_values, name="target_type")
    )
    endpoint_url: Mapped[str] = mapped_column(String(1024))
    headers_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scans: Mapped[list["Scan"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )

    @property
    def headers_preview(self) -> dict[str, str]:
        """Vue redactée des headers — sûre à exposer publiquement.

        Les valeurs des en-têtes sensibles (Authorization, X-API-Key…) sont
        remplacées par `***REDACTED***`. Les en-têtes non sensibles passent
        tels quels. Vide si `headers_json` est null ou invalide.
        """
        # Import local pour éviter une dépendance circulaire au boot.
        from .security.redaction import redact_headers

        if not self.headers_json:
            return {}
        try:
            value = json.loads(self.headers_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        coerced = {str(k): str(v) for k, v in value.items()}
        return redact_headers(coerced)

    @property
    def has_auth(self) -> bool:
        """True si au moins un en-tête sensible non vide est configuré."""
        from .security.redaction import SENSITIVE_HEADER_NAMES

        if not self.headers_json:
            return False
        try:
            value = json.loads(self.headers_json)
        except json.JSONDecodeError:
            return False
        if not isinstance(value, dict):
            return False
        sensitive = {h.lower() for h in SENSITIVE_HEADER_NAMES}
        return any(str(k).lower() in sensitive and v for k, v in value.items())


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    status: Mapped[ScanStatus] = mapped_column(
        SAEnum(ScanStatus, values_callable=_enum_values, name="scan_status"),
        default=ScanStatus.PENDING,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    selected_categories_json: Mapped[str] = mapped_column(Text)
    max_attempts_per_category: Mapped[int] = mapped_column(Integer, default=5)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0)
    successful_attacks: Mapped[int] = mapped_column(Integer, default=0)
    robustness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    target: Mapped[Target] = relationship(back_populates="scans")
    attempts: Mapped[list["AttackAttempt"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    report: Mapped[Optional["Report"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", uselist=False
    )

    @property
    def selected_categories(self) -> list[AttackCategory]:
        """Vue désérialisée de `selected_categories_json`."""
        if not self.selected_categories_json:
            return []
        try:
            raw = json.loads(self.selected_categories_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        return [AttackCategory(c) for c in raw if c in {e.value for e in AttackCategory}]


class AttackAttempt(Base):
    __tablename__ = "attack_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    category: Mapped[AttackCategory] = mapped_column(
        SAEnum(AttackCategory, values_callable=_enum_values, name="attack_category")
    )
    strategy_name: Mapped[str] = mapped_column(String(255))
    attack_prompt: Mapped[str] = mapped_column(Text)
    target_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    judgment: Mapped[Optional[JudgmentVerdict]] = mapped_column(
        SAEnum(JudgmentVerdict, values_callable=_enum_values, name="judgment_verdict"),
        nullable=True,
    )
    judgment_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[Optional[Severity]] = mapped_column(
        SAEnum(Severity, values_callable=_enum_values, name="severity"),
        nullable=True,
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scan: Mapped[Scan] = relationship(back_populates="attempts")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), unique=True
    )
    html_path: Mapped[str] = mapped_column(String(1024))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scan: Mapped[Scan] = relationship(back_populates="report")
