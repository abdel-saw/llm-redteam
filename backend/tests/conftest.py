"""Fixtures partagées."""

from __future__ import annotations

import pytest

from backend.app.services.event_bus import reset_event_bus


@pytest.fixture(autouse=True)
def _reset_event_bus_between_tests():
    """Le bus est un singleton process-wide ; on repart d'un état propre.

    Indispensable parce que `asyncio.Lock` du bus est lié à l'event loop
    courant. Pytest-asyncio crée un loop par test ; sans reset, le lock
    d'un test précédent serait réutilisé sur un loop fermé.
    """
    reset_event_bus()
    yield
    reset_event_bus()
