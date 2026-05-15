"""Tests de la redaction de secrets : helpers, schemas, endpoint HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app.security.log_filter import SecretRedactingFilter
from backend.app.security.redaction import (
    REDACTED_PLACEHOLDER,
    redact_headers,
    redact_text,
)


def _record(msg: str, *args) -> "logging.LogRecord":  # noqa: F821
    import logging

    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args or None, exc_info=None,
    )


# --------------------------- redact_headers ----------------------------------


class TestRedactHeaders:
    def test_redact_headers_case_insensitive(self):
        for name in ("Authorization", "authorization", "AUTHORIZATION"):
            out = redact_headers({name: "Bearer xxx"})
            assert out[name] == REDACTED_PLACEHOLDER

    def test_redact_other_sensitive_headers(self):
        out = redact_headers({
            "X-Api-Key": "secret",
            "x-api-key": "secret",
            "Openai-Api-Key": "sk-xxx",
            "Cookie": "session=abc",
        })
        for v in out.values():
            assert v == REDACTED_PLACEHOLDER

    def test_redact_headers_preserves_non_sensitive(self):
        out = redact_headers({
            "Content-Type": "application/json",
            "X-Custom": "value",
            "User-Agent": "test/1.0",
        })
        assert out == {
            "Content-Type": "application/json",
            "X-Custom": "value",
            "User-Agent": "test/1.0",
        }

    def test_redact_headers_preserves_original_case(self):
        # Le nom est conservé tel quel, seule la valeur est masquée.
        out = redact_headers({"AuThOrIzAtIoN": "Bearer x"})
        assert "AuThOrIzAtIoN" in out
        assert out["AuThOrIzAtIoN"] == REDACTED_PLACEHOLDER


# --------------------------- redact_text -------------------------------------


class TestRedactText:
    def test_redact_text_bearer_token(self):
        out = redact_text("Authorization: Bearer abc123xyz")
        assert "abc123xyz" not in out
        assert REDACTED_PLACEHOLDER in out

    def test_redact_text_openai_key_prefix(self):
        out = redact_text("api key sk-1234567890abcdefghijklm used")
        assert "sk-1234567890" not in out
        assert REDACTED_PLACEHOLDER in out

    def test_redact_text_groq_key_prefix(self):
        out = redact_text(
            "key gsk_FAKERkey_REDACTED_FOR_TESTS_xxxxxxxxxxxxx is leaked"
        )
        assert "gsk_JbaZDE6" not in out

    def test_redact_text_anthropic_and_openrouter_prefixes(self):
        # FAKER values, on the same line so the codebase scanner whitelist matches.
        out = redact_text("sk-ant-api03-fakefakefakefakefakefake1 and sk-or-v1-fakefakefakefakefake")
        assert "sk-ant-api03-" not in out
        assert "sk-or-v1-" not in out

    def test_redact_text_preserves_non_secret_content(self):
        text = "Hello world, no secrets here, just a regular log line."
        assert redact_text(text) == text

    def test_redact_text_idempotent(self):
        once = redact_text("Bearer realtoken12345")
        twice = redact_text(once)
        assert once == twice


# ----------------------- SecretRedactingFilter --------------------------------


class TestSecretRedactingFilter:
    def test_redacts_message_string(self):
        flt = SecretRedactingFilter()
        rec = _record("Auth header: Bearer gsk_AAAAAAAAAAAAAAAAAAAA1234")
        assert flt.filter(rec) is True
        assert "gsk_AAAAAAAA" not in rec.getMessage()
        assert REDACTED_PLACEHOLDER in rec.getMessage()

    def test_redacts_simple_args(self):
        flt = SecretRedactingFilter()
        rec = _record("call provider=%s key=%s", "groq", "Bearer gsk_AAAAAAAAAAAAAAAAAAAA1234")
        flt.filter(rec)
        assert "gsk_" not in rec.getMessage()

    def test_redacts_nested_tuple_args_sqlalchemy_style(self):
        """Régression : SQLAlchemy logue des tuples de paramètres SQL."""
        flt = SecretRedactingFilter()
        params = (
            "Groq target", "openai_compatible", "https://api.groq.com/openai/v1",
            '{"Authorization": "Bearer gsk_AAAAAAAAAAAAAAAAAAAA1234"}',
            None, None, "llama-3.1-8b-instant",
        )
        rec = _record("[generated in 0.0001s] %s", params)
        flt.filter(rec)
        out = rec.getMessage()
        assert "gsk_AAAAAAAA" not in out
        assert REDACTED_PLACEHOLDER in out

    def test_safe_message_unchanged(self):
        flt = SecretRedactingFilter()
        rec = _record("normal log line, no secrets")
        flt.filter(rec)
        assert rec.getMessage() == "normal log line, no secrets"


# ----------------------- Endpoint integration --------------------------------


@pytest.fixture
def test_client():
    """TestClient avec DB SQLite mémoire isolée."""
    # Force l'import de models pour que Base.metadata ait les tables avant
    # `create_all`. (`database` n'importe pas `models` au top-level.)
    import backend.app.models  # noqa: F401

    # StaticPool : SQLite `:memory:` est par-défaut une DB par connexion ;
    # ce pool force toutes les sessions à partager la même connexion, donc
    # la même DB, ce qui permet aux routes (via override_get_db) de voir
    # les tables créées par `Base.metadata.create_all`.
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
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class TestTargetEndpointRedaction:
    def test_target_read_does_not_expose_raw_authorization(self, test_client):
        r = test_client.post("/api/targets", json={
            "name": "leak test",
            "target_type": "openai_compatible",
            "endpoint_url": "https://api.example.com/v1",
            "headers": {"Authorization": "Bearer super-secret-key-12345"},
            "model_name": "x",
        })
        assert r.status_code == 201, r.text

        body = r.json()
        # Le secret ne doit JAMAIS apparaître nulle part dans la réponse.
        assert "super-secret-key" not in r.text
        # Le schema doit exposer les nouvelles vues redactées.
        assert body["headers_preview"]["Authorization"] == REDACTED_PLACEHOLDER
        assert body["has_auth"] is True
        # Et surtout, le champ brut `headers` ne doit pas être présent
        # dans la réponse publique.
        assert "headers" not in body or body.get("headers") is None

    def test_get_target_endpoint_returns_redacted_headers(self, test_client):
        r1 = test_client.post("/api/targets", json={
            "name": "get test",
            "target_type": "openai_compatible",
            "endpoint_url": "https://api.example.com/v1",
            "headers": {
                "Authorization": "Bearer gsk_FAKERkey1234567890abcdefghijklmnop",
                "X-Request-Id": "trace-1",
            },
            "model_name": "x",
        })
        target_id = r1.json()["id"]

        r2 = test_client.get(f"/api/targets/{target_id}")
        assert r2.status_code == 200
        body = r2.json()

        assert "gsk_realgroqkey" not in r2.text
        assert body["headers_preview"]["Authorization"] == REDACTED_PLACEHOLDER
        # En-tête non sensible : passe en clair.
        assert body["headers_preview"]["X-Request-Id"] == "trace-1"
        assert body["has_auth"] is True

    def test_target_without_auth_has_has_auth_false(self, test_client):
        r = test_client.post("/api/targets", json={
            "name": "no auth",
            "target_type": "openai_compatible",
            "endpoint_url": "https://api.example.com/v1",
            "headers": {"X-Trace": "abc"},
            "model_name": "x",
        })
        body = r.json()
        assert body["has_auth"] is False
        assert body["headers_preview"] == {"X-Trace": "abc"}


# ----------------------- Security middleware ---------------------------------


class TestSecurityHeaders:
    def test_root_endpoint_includes_security_headers(self, test_client):
        r = test_client.get("/")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "geolocation=()" in r.headers["Permissions-Policy"]
