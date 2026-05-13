"""Tests d'intégration des routes /api/targets.

L'objectif minimal de ce fichier est de couvrir les endpoints qui ont une
contrainte HTTP spécifique :
- DELETE /api/targets/{id} → 204 No Content (Starlette refuse strictement
  tout body sur ce status, donc un test unitaire qui mock la couche route
  ne suffit pas : il faut faire passer la réponse par la stack ASGI réelle).
- 404 lorsque la cible n'existe pas.

Ce sont précisément les contrats qui échappent aux tests unitaires et
qu'on ne peut valider qu'en bout-en-bout — d'où la nécessité de tests
d'intégration HTTP.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401 — enregistre les tables sur Base.metadata
from backend.app.database import Base, get_db


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
        yield client

    app.dependency_overrides.clear()


class TestDeleteTarget:
    @pytest.mark.asyncio
    async def test_delete_target_returns_204_with_empty_body(self, async_client):
        # Crée une cible.
        r = await async_client.post("/api/targets", json={
            "name": "to-delete",
            "target_type": "openai_compatible",
            "endpoint_url": "https://example.com/v1",
            "model_name": "m",
        })
        assert r.status_code == 201, r.text
        target_id = r.json()["id"]

        # Suppression : status 204 + body vide (Starlette refuse tout body sur
        # un 204 ; un test ASGI fait remonter l'erreur si la stack tente d'en
        # sérialiser un).
        r = await async_client.delete(f"/api/targets/{target_id}")
        assert r.status_code == 204
        assert r.content == b""

        # Confirmation : 404 sur le suivant.
        r = await async_client.get(f"/api/targets/{target_id}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_unknown_target_returns_404(self, async_client):
        r = await async_client.delete("/api/targets/9999")
        assert r.status_code == 404
        assert r.json()["detail"] == "Target not found"
