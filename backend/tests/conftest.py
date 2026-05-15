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


@pytest.fixture(autouse=True)
def _isolate_db_and_reports(tmp_path, monkeypatch):
    """Sandbox `settings.database_url` et `settings.reports_dir` dans
    `tmp_path` pour tous les tests.

    Sans cela, les tests qui déclenchent le lifespan FastAPI (typiquement
    via `TestClient(app)`) appellent `ensure_sqlite_dir(settings.database_url)`,
    qui essaie par défaut de créer `/app/data/`. Ça passe en local Windows
    (création silencieuse d'un dossier sous le drive courant) et dans
    Docker (le Dockerfile crée /app/data avec chown 1000), mais sur un
    runner CI Linux non-root, c'est une `PermissionError: '/app'`.

    Les tests qui veulent un override spécifique (par ex. tester le
    warning « relative-DB-in-Docker ») peuvent re-monkeypatch après —
    leur fixture override celle-ci, puisqu'elles s'exécutent dans le
    même scope `function`.
    """
    # Imports locaux : conftest est chargé très tôt et on évite d'élargir
    # l'arbre d'imports module-load.
    from backend.app.config import settings as _settings

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    monkeypatch.setattr(_settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(_settings, "reports_dir", str(reports_dir))

    # Garde les env vars cohérentes au cas où un sous-process / un
    # `Settings()` re-instancié les relit (cf. tests qui instancient
    # `Settings(...)` directement — ils passent leurs propres params
    # et ignorent ces env vars, donc no-op pour eux).
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("REPORTS_DIR", str(reports_dir))

    yield
