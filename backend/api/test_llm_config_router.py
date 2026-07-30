"""Tests for the LLM config router — CRUD + verify + detect (Story 15.3, FR-MT-72..74).

Run inside Docker:
    docker compose exec api pytest test_llm_config_router.py -v
"""
from __future__ import annotations

import os

os.environ.setdefault("AUTH_PASSWORD", "test-password-llmconfig")
os.environ.setdefault("DB_PATH", "/tmp/test_basira_llm_config.db")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from database import engine, init_db

TEST_USER_ID = 1


@pytest.fixture
def fernet_key(monkeypatch):
    """Ensure FERNET_SECRET_KEY is set so encrypt_key/decrypt_key work in tests."""
    from llm_crypto import generate_fernet_key
    key = generate_fernet_key()
    monkeypatch.setenv("FERNET_SECRET_KEY", key)
    return key


@pytest.fixture
def client():
    """TestClient(app) with require_session overridden to a fixed test user.

    Pattern mirrors test_discovery_job.py's _make_client(): import the real
    main.app, override the require_session dependency, clear overrides after.
    """
    from main import app
    from auth import require_session
    from services.tenant_llm_router import _cache as _router_cache

    init_db()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM user_llm_configs"))
        conn.commit()
    _router_cache.clear()

    def _fake_session():
        return {"id": TEST_USER_ID, "email": "test@test.com", "org_id": None}

    app.dependency_overrides[require_session] = _fake_session
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.clear()
    _router_cache.clear()


def test_list_providers(client):
    """GET /api/llm-config/providers retourne la liste des descripteurs."""
    resp = client.get("/api/llm-config/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["name"] == "openrouter" for p in data)
    assert any(p["name"] == "ollama" for p in data)


def test_put_config_encrypts_key(client, fernet_key):
    """PUT /api/llm-config/scorer → clé chiffrée en DB."""
    resp = client.put("/api/llm-config/scorer", json={
        "provider": "openrouter",
        "model": "google/gemini-flash-1.5",
        "api_key": "sk-or-test-key",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT api_key_enc FROM user_llm_configs WHERE user_id=:uid AND role='scorer'"),
            {"uid": TEST_USER_ID},
        ).fetchone()
    assert row is not None
    assert row[0] is not None
    assert row[0] != b"sk-or-test-key"
    assert b"sk-or-test-key" not in row[0]


def test_put_without_api_key_preserves_existing_key(client, fernet_key):
    """PUT sans api_key ne réécrit pas la clé existante (Story 15.5)."""
    client.put("/api/llm-config/scorer", json={
        "provider": "openrouter", "model": "google/gemini-flash-1.5", "api_key": "sk-or-original",
    })
    with engine.connect() as conn:
        original_enc = conn.execute(
            text("SELECT api_key_enc FROM user_llm_configs WHERE user_id=:uid AND role='scorer'"),
            {"uid": TEST_USER_ID},
        ).fetchone()[0]

    # Edit form submits without api_key (never pre-filled) — model change only.
    resp = client.put("/api/llm-config/scorer", json={
        "provider": "openrouter", "model": "google/gemini-2.0-flash", "api_key": None,
    })
    assert resp.status_code == 200

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT model, api_key_enc FROM user_llm_configs WHERE user_id=:uid AND role='scorer'"),
            {"uid": TEST_USER_ID},
        ).fetchone()
    assert row[0] == "google/gemini-2.0-flash"
    assert row[1] == original_enc  # key untouched, not wiped to NULL


def test_get_config_no_key_in_response(client, fernet_key):
    """GET /api/llm-config ne retourne pas api_key en clair."""
    client.put("/api/llm-config/scorer", json={
        "provider": "openrouter", "model": "gemini-flash-1.5", "api_key": "sk-or-secret"
    })
    resp = client.get("/api/llm-config")
    assert resp.status_code == 200
    for item in resp.json():
        assert "api_key" not in item or item.get("api_key") is None
        assert item.get("api_key_configured") is True


def test_delete_config(client, fernet_key):
    """DELETE /api/llm-config/scorer supprime la config."""
    client.put("/api/llm-config/scorer", json={
        "provider": "openrouter", "model": "gemini", "api_key": "sk-or-x"
    })
    resp = client.delete("/api/llm-config/scorer")
    assert resp.status_code == 200
    resp2 = client.get("/api/llm-config")
    roles = [item["role"] for item in resp2.json()]
    assert "scorer" not in roles


def test_detect_openrouter(client):
    resp = client.post("/api/llm-config/detect", json={"api_key": "sk-or-abc"})
    assert resp.json()["provider"] == "openrouter"


def test_detect_anthropic(client):
    resp = client.post("/api/llm-config/detect", json={"api_key": "sk-ant-xyz"})
    assert resp.json()["provider"] == "anthropic"


def test_put_onboarding_role_accepted(client, fernet_key):
    """PUT /api/llm-config/onboarding → accepté (rôle dédié bootstrap/discovery, Story MT-LLM-gate)."""
    resp = client.put("/api/llm-config/onboarding", json={
        "provider": "openrouter", "model": "google/gemini-flash-1.5", "api_key": "sk-or-onboard",
    })
    assert resp.status_code == 200
    resp2 = client.get("/api/llm-config")
    roles = [item["role"] for item in resp2.json()]
    assert "onboarding" in roles


def test_invalid_role_rejected(client):
    resp = client.put("/api/llm-config/unknown_role", json={
        "provider": "openrouter", "model": "gemini", "api_key": "sk-or-x"
    })
    assert resp.status_code == 400


def test_verify_success(client):
    """POST /api/llm-config/verify avec bonne clé → {ok: true} (Gherkin scenario)."""
    with patch("routers.llm_config.verify_connection", new=AsyncMock(return_value={"ok": True})):
        resp = client.post("/api/llm-config/verify", json={
            "provider": "openrouter", "api_key": "sk-or-valid",
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
