"""Tests pour backend.app.utils.db_path.

L'utilitaire est responsable d'éviter le bug
`unable to open database file` quand SQLite tente d'ouvrir un fichier
dans un dossier inexistant — bug récurrent dans les déploiements
Docker avec utilisateur non-root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.utils.db_path import (
    ensure_sqlite_dir,
    warn_if_relative_in_docker,
)


class TestEnsureSqliteDir:
    def test_creates_missing_parent(self, tmp_path):
        db_path = tmp_path / "newdir" / "nested" / "x.db"
        assert not db_path.parent.exists()
        ensure_sqlite_dir(f"sqlite:///{db_path}")
        assert db_path.parent.is_dir()

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "subdir" / "x.db"
        ensure_sqlite_dir(f"sqlite:///{db_path}")
        # Deuxième appel : ne doit pas lever, le dir reste là.
        ensure_sqlite_dir(f"sqlite:///{db_path}")
        assert db_path.parent.is_dir()

    def test_noop_for_memory_url(self):
        # Ne doit ni planter ni créer un dossier ":memory:".
        ensure_sqlite_dir("sqlite:///:memory:")
        ensure_sqlite_dir("sqlite://")
        assert not Path(":memory:").exists()

    def test_noop_for_non_sqlite_url(self):
        # No-op : aucune exception, aucun side effect filesystem.
        ensure_sqlite_dir("postgresql://user:pw@host:5432/db")
        ensure_sqlite_dir("mysql+pymysql://u:p@host/db")
        ensure_sqlite_dir("postgresql+asyncpg://u:p@host/db")

    def test_handles_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # `sqlite:///./subdir/x.db` → chemin relatif "./subdir/x.db".
        # Après chdir vers tmp_path, le dossier doit apparaître.
        ensure_sqlite_dir("sqlite:///./subdir/x.db")
        assert (tmp_path / "subdir").is_dir()

    def test_handles_absolute_path_with_four_slashes(self, tmp_path):
        # Format SQLAlchemy pour absolu sous Unix : sqlite:////abs/path.db
        # Sous Windows on simule via tmp_path (résolu absolu).
        abs_db = tmp_path / "absdir" / "x.db"
        url = f"sqlite:///{abs_db}"  # Path absolu sera détecté par make_url
        ensure_sqlite_dir(url)
        assert abs_db.parent.is_dir()

    def test_malformed_url_is_silent_noop(self):
        # On ne veut pas faire planter le startup pour une URL bizarre.
        ensure_sqlite_dir("this-is-not-a-url")
        ensure_sqlite_dir("")


class TestWarnIfRelativeInDocker:
    def test_returns_none_for_absolute_path(self, tmp_path):
        # En passant un chemin absolu, on doit retourner None, même si
        # on est en environnement de test où le détecteur Docker peut
        # retourner True selon la CI.
        assert warn_if_relative_in_docker(
            f"sqlite:///{tmp_path}/x.db"
        ) is None

    def test_returns_none_for_memory_url(self):
        assert warn_if_relative_in_docker("sqlite:///:memory:") is None

    def test_returns_none_for_non_sqlite(self):
        assert warn_if_relative_in_docker("postgresql://u@host/db") is None

    def test_returns_warning_when_relative_and_in_docker(
        self, monkeypatch, tmp_path
    ):
        # Simule un environnement Docker via le sentinel
        # `/.dockerenv` — on monkeypatch _looks_like_docker.
        from backend.app.utils import db_path as mod
        monkeypatch.setattr(mod, "_looks_like_docker", lambda: True)
        warning = warn_if_relative_in_docker("sqlite:///./local.db")
        assert warning is not None
        assert "relative" in warning.lower()
        assert "sqlite:////app/data" in warning  # rappelle le format recommandé

    def test_returns_none_when_relative_but_not_in_docker(self, monkeypatch):
        from backend.app.utils import db_path as mod
        monkeypatch.setattr(mod, "_looks_like_docker", lambda: False)
        assert warn_if_relative_in_docker("sqlite:///./local.db") is None
