"""Bus d'événements en mémoire pour le streaming SSE.

Le moteur d'attaque (`attack_engine`) publie un `ScanEvent` après chaque
tentative ; la route `/api/scans/{id}/stream` souscrit pour récupérer le
flux et le pousser au client en SSE.

Particularités :
- Un buffer (deque) par scan_id mémorise les 100 derniers events pour
  permettre aux clients connectés en cours de route de rattraper l'historique.
- Si un client est lent (queue pleine), on drop l'event et on log un warning
  plutôt que de bloquer le moteur. La queue par client a maxsize=200.
- `close_scan(scan_id)` marque le scan comme terminé : les subscribers
  reçoivent un sentinel et le côté SSE peut fermer proprement. Le buffer
  est conservé pour les late subscribers (replay d'un scan déjà fini).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Optional

from .attack_engine import ScanEvent

logger = logging.getLogger(__name__)

# Sentinel object utilisé pour signaler la fin d'un flux à un subscriber.
SENTINEL: Any = object()

_SUBSCRIBER_QUEUE_MAXSIZE = 200
_BUFFER_MAXLEN = 100


class ScanEventBus:
    """Bus pub/sub par scan_id, async-safe sur un seul event loop."""

    def __init__(self) -> None:
        self._subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)
        self._buffers: dict[int, deque[ScanEvent]] = defaultdict(
            lambda: deque(maxlen=_BUFFER_MAXLEN)
        )
        self._closed: set[int] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, scan_id: int) -> asyncio.Queue:
        """Crée une queue, rejoue le buffer, puis branche sur le flux live.

        Si le scan est déjà clos, la queue contient le buffer + SENTINEL et
        le consommateur reçoit l'historique complet puis termine. Sinon la
        queue continue à recevoir les events publiés en live.
        """
        async with self._lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
            # Replay des events bufferisés.
            for event in self._buffers[scan_id]:
                self._enqueue_or_drop(queue, event, scan_id, "replay")
            if scan_id in self._closed:
                self._enqueue_or_drop(queue, SENTINEL, scan_id, "replay-sentinel")
                return queue
            self._subscribers[scan_id].append(queue)
            return queue

    async def unsubscribe(self, scan_id: int, queue: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._subscribers.get(scan_id)
            if subs and queue in subs:
                subs.remove(queue)

    async def publish(self, scan_id: int, event: ScanEvent) -> None:
        """Bufferise l'event et le pousse à tous les subscribers actifs."""
        async with self._lock:
            if scan_id in self._closed:
                logger.warning(
                    "publish after close_scan(%d) — event %s ignored",
                    scan_id, event.type,
                )
                return
            self._buffers[scan_id].append(event)
            for queue in list(self._subscribers[scan_id]):
                self._enqueue_or_drop(queue, event, scan_id, "live")

    async def close_scan(self, scan_id: int) -> None:
        """Marque le scan terminé, envoie un sentinel aux subscribers actifs.

        Le buffer est conservé : un client qui se connecte plus tard
        recevra l'historique complet + un sentinel pour fermer le flux.
        """
        async with self._lock:
            self._closed.add(scan_id)
            for queue in list(self._subscribers.get(scan_id, [])):
                self._enqueue_or_drop(queue, SENTINEL, scan_id, "close")
            self._subscribers[scan_id] = []

    @staticmethod
    def _enqueue_or_drop(
        queue: asyncio.Queue, item: Any, scan_id: int, source: str
    ) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning(
                "scan %d %s queue full — dropping event (subscriber too slow)",
                scan_id, source,
            )

    # ------------- Helpers utilisés par les tests / introspection -----------

    def is_closed(self, scan_id: int) -> bool:
        return scan_id in self._closed

    def buffer_size(self, scan_id: int) -> int:
        return len(self._buffers.get(scan_id, ()))

    def subscriber_count(self, scan_id: int) -> int:
        return len(self._subscribers.get(scan_id, []))


_bus: Optional[ScanEventBus] = None


def get_event_bus() -> ScanEventBus:
    """Singleton lazy."""
    global _bus
    if _bus is None:
        _bus = ScanEventBus()
    return _bus


def reset_event_bus() -> None:
    """Utile pour les tests : repart d'un bus vide."""
    global _bus
    _bus = None
