"""Tests for onboarding Step 3 — LLM config (Story 15.4, FR-MT-77).

Run inside Docker:
    docker compose exec api pytest test_onboarding_step3.py -v
"""
from __future__ import annotations

import os

os.environ.setdefault("AUTH_PASSWORD", "test-password-onboarding-step3")
os.environ.setdefault("DB_PATH", "/tmp/test_basira_onboarding_step3.db")

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
    """TestClient(app) with require_session overridden to a fixed test user."""
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


def test_step3_saves_scorer_embedder(client, fernet_key):
    """POST /api/onboarding/step3 sauvegarde scorer + review + ask + onboarding + embedder."""
    resp = client.post("/api/onboarding/step3", json={
        "provider": "openrouter",
        "model": "google/gemini-flash-1.5",
        "api_key": "sk-or-test",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT role, provider, api_key_enc FROM user_llm_configs WHERE user_id=:uid ORDER BY role"),
            {"uid": TEST_USER_ID},
        ).fetchall()
    roles = {row[0]: row for row in rows}
    assert set(roles.keys()) == {"scorer", "review", "ask", "onboarding", "embedder"}
    assert roles["scorer"][1] == "openrouter"
    assert roles["scorer"][2] is not None  # encrypted key present
    assert roles["review"][1] == "openrouter"
    assert roles["ask"][1] == "openrouter"
    # Story MT-LLM-gate: bootstrap/discovery resolve via "onboarding" — without
    # this row, has_user_llm_config("onboarding") gates them out right after
    # this step completes, even though the user just configured their LLM.
    assert roles["onboarding"][1] == "openrouter"
    assert roles["onboarding"][2] is not None
    assert roles["embedder"][1] == "ollama"
    assert roles["embedder"][2] is None  # no key for Ollama


def test_step3_ollama_no_key(client):
    """Ollama provider accepté sans api_key."""
    resp = client.post("/api/onboarding/step3", json={
        "provider": "ollama",
        "model": "llama3.2:3b",
        "api_key": None,
        "base_url": "http://localhost:11434",
    })
    assert resp.status_code == 200

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT provider, api_key_enc FROM user_llm_configs WHERE user_id=:uid AND role='scorer'"),
            {"uid": TEST_USER_ID},
        ).fetchone()
    assert row is not None
    assert row[0] == "ollama"
    assert row[1] is None
