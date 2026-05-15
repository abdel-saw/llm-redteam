"""Helpers pour préparer le système de fichiers avant l'ouverture de
la base SQLite.

Le but : éviter le grand classique
`sqlalchemy.exc.OperationalError: unable to open database file`
quand l'utilisateur non-root du container Docker (uid 1000) ne peut
pas écrire dans le répertoire où SQLite tente de créer son fichier.

Deux fonctions, toutes deux idempotentes et sans effet de bord pour
les autres backends (PostgreSQL, MySQL, etc.) ou pour SQLite en
mémoire.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.engine.url import make_url

logger = logging.getLogger(__name__)


def ensure_sqlite_dir(database_url: str) -> None:
    """Crée le dossier parent du fichier SQLite si nécessaire.

    No-op pour :
    - les URL non-SQLite (postgresql://, mysql://, ...)
    - SQLite en mémoire (`sqlite:///:memory:` ou `sqlite://`)
    - les fichiers dont le parent existe déjà

    Utilise `pathlib.Path.mkdir(parents=True, exist_ok=True)`, donc
    appelable plusieurs fois sans crash.
    """
    db_path = _sqlite_file_path(database_url)
    if db_path is None:
        return
    parent = db_path.parent
    # Path('.') = répertoire courant — déjà existant par construction,
    # mais on appelle quand même mkdir(exist_ok=True) pour rester simple.
    parent.mkdir(parents=True, exist_ok=True)


def warn_if_relative_in_docker(database_url: str) -> Optional[str]:
    """Retourne un message de warning si on tourne en container et que
    `DATABASE_URL` utilise un chemin SQLite relatif.

    Un chemin relatif dans un container Docker écrit la base dans CWD
    (typiquement `/app`), qui n'est pas un volume persistant. Le
    container redémarre → la base disparaît.

    Retourne `None` quand tout va bien (chemin absolu, pas en
    container, base non-SQLite, ou base en mémoire).
    """
    db_path = _sqlite_file_path(database_url)
    if db_path is None:
        return None
    if db_path.is_absolute():
        return None
    if not _looks_like_docker():
        return None
    return (
        f"DATABASE_URL='{database_url}' uses a relative SQLite path "
        f"({db_path}) but the app appears to be running inside a "
        f"container. The DB will be written under CWD which is "
        f"typically not persistent. Use an absolute path like "
        f"sqlite:////app/data/red-agent-s.db."
    )


def emit_startup_db_warnings(database_url: str) -> None:
    """Helper de convenance appelé depuis le startup event.

    Logue (niveau WARNING) le résultat de `warn_if_relative_in_docker`
    si applicable.
    """
    msg = warn_if_relative_in_docker(database_url)
    if msg:
        logger.warning(msg)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _sqlite_file_path(database_url: str) -> Optional[Path]:
    """Retourne le `Path` du fichier SQLite, ou `None` si l'URL n'est
    pas une URL SQLite file-based.

    SQLAlchemy gère pour nous le parsing : `sqlite:///./x.db`,
    `sqlite:////abs/x.db`, `sqlite:///:memory:`, etc.
    """
    try:
        url = make_url(database_url)
    except Exception:  # noqa: BLE001 - URL malformée -> on ne fait rien
        return None
    backend = url.drivername.split("+", 1)[0]
    if backend != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser()


def _looks_like_docker() -> bool:
    """Heuristique simple : présence du fichier `/.dockerenv` créé par
    Docker, ou cwd dans `/app` (notre WORKDIR conventionnel)."""
    if Path("/.dockerenv").exists():
        return True
    try:
        cwd = Path.cwd().resolve()
    except (OSError, FileNotFoundError):
        return False
    return cwd == Path("/app") or Path("/app") in cwd.parents
