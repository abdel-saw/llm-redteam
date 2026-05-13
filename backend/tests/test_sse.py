"""Tests du bus d'événements et de l'endpoint SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401  — enregistre les tables sur Base.metadata
from backend.app.database import Base, get_db
from backend.app.enums import ScanStatus, TargetType
from backend.app.models import Scan, Target
from backend.app.services.attack_engine import ScanEvent
from backend.app.services.event_bus import SENTINEL, ScanEventBus, get_event_bus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _evt(kind: str, **payload) -> ScanEvent:
    return ScanEvent(type=kind, timestamp=_now(), payload=payload)


# ----------------------------- ScanEventBus ----------------------------------


class TestScanEventBus:
    @pytest.mark.asyncio
    async def test_publish_delivers_to_all_subscribers(self):
        bus = ScanEventBus()
        q1 = await bus.subscribe(1)
        q2 = await bus.subscribe(1)

        await bus.publish(1, _evt("scan_started"))
        await bus.publish(1, _evt("attempt_completed"))

        assert q1.qsize() == 2
        assert q2.qsize() == 2
        assert (await q1.get()).type == "scan_started"
        assert (await q1.get()).type == "attempt_completed"

    @pytest.mark.asyncio
    async def test_late_subscriber_gets_buffered_history(self):
        bus = ScanEventBus()
        await bus.publish(7, _evt("scan_started"))
        await bus.publish(7, _evt("attempt_completed", id=1))
        await bus.publish(7, _evt("attempt_completed", id=2))

        q = await bus.subscribe(7)
        assert q.qsize() == 3
        types = [(await q.get()).type for _ in range(3)]
        assert types == ["scan_started", "attempt_completed", "attempt_completed"]

    @pytest.mark.asyncio
    async def test_subscribe_to_closed_scan_replays_then_sentinel(self):
        bus = ScanEventBus()
        await bus.publish(9, _evt("scan_started"))
        await bus.publish(9, _evt("scan_completed", score=42))
        await bus.close_scan(9)

        q = await bus.subscribe(9)
        items: list = []
        while True:
            item = await q.get()
            items.append(item)
            if item is SENTINEL:
                break
        types = [getattr(i, "type", "SENTINEL") for i in items]
        assert types == ["scan_started", "scan_completed", "SENTINEL"]

    @pytest.mark.asyncio
    async def test_drops_events_when_queue_full(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        bus = ScanEventBus()
        q = await bus.subscribe(3)
        # On gonfle artificiellement la queue d'un subscriber pour qu'elle
        # sature, sans la consommer.
        for i in range(220):
            await bus.publish(3, _evt("attempt_completed", n=i))

        # La queue plafonne à 200 events ; les 20 derniers sont droppés et
        # un warning est loggé.
        assert q.qsize() <= 200
        assert any("queue full" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_close_scan_pushes_sentinel_to_active_subscribers(self):
        bus = ScanEventBus()
        q = await bus.subscribe(5)
        await bus.publish(5, _evt("scan_started"))
        await bus.close_scan(5)

        first = await q.get()
        second = await q.get()
        assert first.type == "scan_started"
        assert second is SENTINEL


# ----------------------------- Endpoint SSE ----------------------------------


@pytest_asyncio.fixture
async def async_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    Base.metadata.create_all(engine)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    from backend.app.main import app
    app.dependency_overrides[get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # On expose la TestSession factory pour que les tests créent des entités.
        client.test_session_factory = TestSession  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()


def _create_scan(session_factory, scan_id_hint=None) -> int:
    with session_factory() as s:
        target = Target(
            name="t",
            target_type=TargetType.OPENAI_COMPATIBLE,
            endpoint_url="https://api.example.com/v1",
            model_name="m",
        )
        s.add(target)
        s.flush()
        scan = Scan(
            target_id=target.id,
            status=ScanStatus.COMPLETED,
            selected_categories_json='["prompt_injection"]',
            max_attempts_per_category=1,
        )
        s.add(scan)
        s.commit()
        return scan.id


def _parse_sse(body: str) -> list[dict]:
    """Parse le format `event: X\\ndata: Y\\n\\n` en liste de dicts."""
    events: list[dict] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[7:]
            elif line.startswith("data: "):
                ev["data"] = line[6:]
        if ev:
            events.append(ev)
    return events


class TestStreamEndpoint:
    @pytest.mark.asyncio
    async def test_stream_replays_buffered_events_then_closes(self, async_client):
        scan_id = _create_scan(async_client.test_session_factory)

        bus = get_event_bus()
        await bus.publish(scan_id, _evt("scan_started", scan_id=scan_id))
        await bus.publish(scan_id, _evt("attempt_completed", attempt_id=1))
        await bus.publish(scan_id, _evt("scan_completed", robustness_score=80.0))
        await bus.close_scan(scan_id)

        async with async_client.stream("GET", f"/api/scans/{scan_id}/stream") as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk

        # Le flux SSE concatène les 3 events bufferisés.
        # On vérifie via substrings (plus robuste que parser ligne-à-ligne
        # selon le formatage exact de sse_starlette).
        assert "event: scan_started" in body, body[:500]
        assert "event: attempt_completed" in body, body[:500]
        assert "event: scan_completed" in body, body[:500]
        # Chaque ligne data: contient bien le JSON {type, timestamp, payload}.
        assert '"type": "scan_started"' in body
        assert '"type": "scan_completed"' in body

    @pytest.mark.asyncio
    async def test_stream_returns_404_for_unknown_scan(self, async_client):
        resp = await async_client.get("/api/scans/9999/stream")
        assert resp.status_code == 404
