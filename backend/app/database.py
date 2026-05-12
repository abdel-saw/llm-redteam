from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine = create_engine(
    settings.database_url,
    echo=settings.is_dev,
    future=True,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Classe de base ORM partagée par tous les modèles."""


def get_db() -> Generator[Session, None, None]:
    """Dépendance FastAPI : session SQLAlchemy à durée de requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crée les tables manquantes au démarrage applicatif."""
    # L'import est volontairement local : il garantit que tous les modèles
    # sont enregistrés sur `Base.metadata` avant `create_all`, sans
    # introduire de dépendance circulaire au moment du chargement.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
