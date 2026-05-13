"""Tests d'intégration légers du moteur d'attaque (SQLite mémoire)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.enums import (
    AttackCategory,
    JudgmentVerdict,
    ScanStatus,
    Severity,
    TargetType,
)
from backend.app.models import Scan, Target
from backend.app.services.attack_engine import AttackEngine
from backend.app.services.judge import Judgment
from backend.app.services.target_adapter import AdapterResponse, OpenAICompatibleAdapter


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


@pytest.fixture
def scan_with_target(db_session_factory):
    with db_session_factory() as s:
        target = Target(
            name="test target",
            target_type=TargetType.OPENAI_COMPATIBLE,
            endpoint_url="https://api.example.com/v1",
            model_name="x",
            headers_json=json.dumps({"Authorization": "Bearer fake"}),
        )
        s.add(target)
        s.flush()
        scan = Scan(
            target_id=target.id,
            status=ScanStatus.PENDING,
            selected_categories_json=json.dumps(["prompt_injection"]),
            max_attempts_per_category=2,
        )
        s.add(scan)
        s.commit()
        return scan.id


def _make_judge(verdict: JudgmentVerdict, severity: Severity = Severity.LOW) -> MagicMock:
    judge = MagicMock()

    async def fake_judge(*args, **kwargs):
        return Judgment(verdict=verdict, severity=severity, reasoning="mock")

    judge.judge = fake_judge
    return judge


class TestAttackEngine:
    @pytest.mark.asyncio
    async def test_run_scan_full_failure_path_gives_score_100(
        self, db_session_factory, scan_with_target, monkeypatch
    ):
        """Toutes les tentatives échouent (verdict=failure) → ASR=0 → score=100."""

        async def fake_send(self, prompt):
            return AdapterResponse(
                response_text="I cannot help with that request.",
                raw_response={}, latency_ms=12, status_code=200,
            )

        monkeypatch.setattr(OpenAICompatibleAdapter, "send", fake_send)

        client = MagicMock()
        engine = AttackEngine(client, _make_judge(JudgmentVerdict.FAILURE), db_session_factory)
        await engine.run_scan(scan_with_target)

        with db_session_factory() as s:
            scan = s.get(Scan, scan_with_target)
            assert scan.status == ScanStatus.COMPLETED
            assert scan.total_attempts == 2
            assert scan.successful_attacks == 0
            assert scan.robustness_score == 100.0
            assert len(scan.attempts) == 2
            for a in scan.attempts:
                assert a.judgment == JudgmentVerdict.FAILURE
                assert a.category == AttackCategory.PROMPT_INJECTION

    @pytest.mark.asyncio
    async def test_run_scan_all_success_gives_score_0(
        self, db_session_factory, scan_with_target, monkeypatch
    ):
        async def fake_send(self, prompt):
            return AdapterResponse(
                response_text="PWNED", raw_response={}, latency_ms=8, status_code=200,
            )

        monkeypatch.setattr(OpenAICompatibleAdapter, "send", fake_send)

        client = MagicMock()
        engine = AttackEngine(
            client, _make_judge(JudgmentVerdict.SUCCESS, Severity.HIGH), db_session_factory
        )
        await engine.run_scan(scan_with_target)

        with db_session_factory() as s:
            scan = s.get(Scan, scan_with_target)
            assert scan.status == ScanStatus.COMPLETED
            assert scan.successful_attacks == 2
            assert scan.robustness_score == 0.0

    @pytest.mark.asyncio
    async def test_run_scan_adapter_errors_marked_in_attempts(
        self, db_session_factory, scan_with_target, monkeypatch
    ):
        """Si l'adapter plante, les tentatives sont enregistrées en error."""

        async def boom(self, prompt):
            raise RuntimeError("network down")

        monkeypatch.setattr(OpenAICompatibleAdapter, "send", boom)

        client = MagicMock()
        engine = AttackEngine(client, _make_judge(JudgmentVerdict.FAILURE), db_session_factory)
        await engine.run_scan(scan_with_target)

        with db_session_factory() as s:
            scan = s.get(Scan, scan_with_target)
            assert scan.status == ScanStatus.COMPLETED
            assert scan.total_attempts == 2
            # 100% d'erreurs > seuil 30% → robustness_score = None
            assert scan.robustness_score is None
            for a in scan.attempts:
                assert a.judgment == JudgmentVerdict.ERROR
                assert "network down" in (a.error or "")

    @pytest.mark.asyncio
    async def test_run_scan_emits_events(
        self, db_session_factory, scan_with_target, monkeypatch
    ):
        async def fake_send(self, prompt):
            return AdapterResponse(
                response_text="ok", raw_response={}, latency_ms=5, status_code=200,
            )

        monkeypatch.setattr(OpenAICompatibleAdapter, "send", fake_send)

        events = []

        async def collect(event):
            events.append(event)

        client = MagicMock()
        engine = AttackEngine(client, _make_judge(JudgmentVerdict.FAILURE), db_session_factory)
        await engine.run_scan(scan_with_target, on_event=collect)

        types = [e.type for e in events]
        assert types[0] == "scan_started"
        assert types[-1] == "scan_completed"
        assert types.count("attempt_started") == 2
        assert types.count("attempt_completed") == 2
        assert types.count("scan_progress") == 2
