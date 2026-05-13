"""Route SSE : flux d'événements en temps réel d'un scan."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..database import get_db
from ..models import Scan
from ..services.event_bus import SENTINEL, get_event_bus

logger = logging.getLogger(__name__)
router = APIRouter()

_RETRY_MS = 5000  # délai de reconnexion suggéré au client
_PING_INTERVAL_S = 15


@router.get(
    "/{scan_id}/stream",
    summary="Flux SSE des événements d'un scan",
)
async def stream_scan(scan_id: int, db: Session = Depends(get_db)) -> EventSourceResponse:
    if db.get(Scan, scan_id) is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        bus = get_event_bus()
        queue = await bus.subscribe(scan_id)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    # Pas d'event depuis 60s : on continue (le ping de
                    # sse_starlette s'occupe de garder la connexion ouverte).
                    continue
                if item is SENTINEL:
                    logger.debug("scan %d stream: SENTINEL received, closing", scan_id)
                    break
                yield {
                    "event": item.type,
                    "data": json.dumps({
                        "type": item.type,
                        "timestamp": item.timestamp.isoformat(),
                        "payload": item.payload,
                    }, ensure_ascii=False),
                    "retry": _RETRY_MS,
                }
        finally:
            await bus.unsubscribe(scan_id, queue)

    return EventSourceResponse(event_generator(), ping=_PING_INTERVAL_S)
