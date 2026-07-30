"""Tests for GET /api/internal/users/{user_id}/llm-config (Story MT-LLM-gate).

scorer.py (separate container, no DB access) calls this endpoint to resolve a
tenant's LLM config. Mirrors the auth-check pattern of neighboring
/api/internal/users/{user_id}/* endpoints in routers/internal.py.
"""
from __future__ import annotations

import os

os.environ.setdefault("AUTH_PASSWORD", "test-password-internal-llm")
os.environ.setdefault("DB_PATH", "/tmp/test_basira_internal_llm.db")
os.environ.setdefault("API_SECRET", "test-internal-secret")

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def test_wrong_secret_returns_403(client):
    resp = client.get(
        "/api/internal/users/1/llm-config",
        headers={"X-Internal-Secret": "wrong-secret"},
    )
    assert resp.status_code == 403


def test_missing_secret_returns_422(client):
    resp = client.get("/api/internal/users/1/llm-config")
    assert resp.status_code == 422  # required header missing


def test_valid_secret_resolves_config(client):
    fake_config = MagicMock(
        provider="openrouter", model="google/gemini-flash-1.5",
        api_key="sk-or-tenant", base_url=None, source="user",
    )
    fake_router_instance = MagicMock()
    fake_router_instance.get_config.return_value = fake_config

    with patch("services.tenant_llm_router.TenantLLMRouter", lambda user_id: fake_router_instance):
        resp = client.get(
            "/api/internal/users/1/llm-config",
            headers={"X-Internal-Secret": "test-internal-secret"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openrouter"
    assert data["api_key"] == "sk-or-tenant"
    assert data["source"] == "user"
    fake_router_instance.get_config.assert_called_once_with("scorer")


def test_role_query_param_passed_through(client):
    fake_config = MagicMock(
        provider="ollama", model="mistral", api_key=None,
        base_url="http://host.docker.internal:11434", source="env",
    )
    fake_router_instance = MagicMock()
    fake_router_instance.get_config.return_value = fake_config

    with patch("services.tenant_llm_router.TenantLLMRouter", lambda user_id: fake_router_instance):
        resp = client.get(
            "/api/internal/users/1/llm-config?role=onboarding",
            headers={"X-Internal-Secret": "test-internal-secret"},
        )

    assert resp.status_code == 200
    fake_router_instance.get_config.assert_called_once_with("onboarding")
