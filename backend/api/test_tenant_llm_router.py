"""Tests TenantLLMRouter — résolution, fallback, isolation, cache (Story 15.2, FR-MT-75, FR-MT-76).

Run inside Docker:
    docker compose exec api pytest test_tenant_llm_router.py -v
"""
from unittest.mock import MagicMock, patch

import pytest

from services.tenant_llm_router import TenantLLMRouter, _cache


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def fernet_key(monkeypatch):
    """Ensure FERNET_SECRET_KEY is set so encrypt_key/decrypt_key work in tests."""
    from llm_crypto import generate_fernet_key
    key = generate_fernet_key()
    monkeypatch.setenv("FERNET_SECRET_KEY", key)
    return key


def test_from_env_fallback(monkeypatch):
    """Sans config DB → retourne config depuis env vars."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-global")
    monkeypatch.setenv("SCORER_MODEL", "google/gemini-flash-1.5")
    with patch("services.tenant_llm_router.get_llm_config", return_value=None):
        config = TenantLLMRouter(user_id=99).get_config("scorer")
    assert config.source == "env"
    assert config.api_key == "sk-or-global"


def test_from_db_user(monkeypatch, fernet_key):
    """Config DB user → priorité sur env vars."""
    from llm_crypto import encrypt_key
    enc = encrypt_key("sk-or-user2")
    mock_row = MagicMock(provider="openrouter", model="gpt-4o-mini",
                         api_key_enc=enc, base_url=None)
    with patch("services.tenant_llm_router.get_llm_config", return_value=mock_row):
        config = TenantLLMRouter(user_id=2).get_config("scorer")
    assert config.source == "user"
    assert config.api_key == "sk-or-user2"


def test_isolation_user1_vs_user2(monkeypatch, fernet_key):
    """ISOLATION: user_id=2 ne peut PAS utiliser la clé de user_id=1."""
    from llm_crypto import encrypt_key
    enc_user1 = encrypt_key("sk-or-user1-secret")
    mock_row_user1 = MagicMock(provider="openrouter", model="gpt-4o",
                                api_key_enc=enc_user1, base_url=None)

    def fake_get_llm_config(db, user_id, role):
        if user_id == 1:
            return mock_row_user1
        return None  # user_id=2 n'a pas de config

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-global")
    with patch("services.tenant_llm_router.get_llm_config", side_effect=fake_get_llm_config):
        config2 = TenantLLMRouter(user_id=2).get_config("scorer")

    assert config2.api_key != "sk-or-user1-secret"
    assert config2.source == "env"


def test_cache_invalidate(monkeypatch, fernet_key):
    """invalidate(user_id) vide le cache pour ce user."""
    with patch("services.tenant_llm_router.get_llm_config", return_value=None):
        monkeypatch.setenv("OPENROUTER_API_KEY", "global")
        TenantLLMRouter(user_id=5).get_config("scorer")
    assert (5, "scorer") in _cache
    TenantLLMRouter.invalidate(user_id=5)
    assert (5, "scorer") not in _cache


def test_onboarding_role_env_fallback(monkeypatch):
    """role='onboarding' (bootstrap/discovery) resolves like scorer: openrouter + SCORER_MODEL default."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-global")
    monkeypatch.setenv("SCORER_MODEL", "google/gemini-flash-1.5")
    with patch("services.tenant_llm_router.get_llm_config", return_value=None):
        config = TenantLLMRouter(user_id=8).get_config("onboarding")
    assert config.source == "env"
    assert config.provider == "openrouter"
    assert config.api_key == "sk-or-global"
    assert config.model == "google/gemini-flash-1.5"


def test_onboarding_role_from_db_user(monkeypatch, fernet_key):
    """role='onboarding' config DB user prend priorité sur env vars, comme les autres rôles."""
    from llm_crypto import encrypt_key
    enc = encrypt_key("sk-or-onboarding-user")
    mock_row = MagicMock(provider="openrouter", model="gpt-4o-mini",
                         api_key_enc=enc, base_url=None)
    with patch("services.tenant_llm_router.get_llm_config", return_value=mock_row):
        config = TenantLLMRouter(user_id=3).get_config("onboarding")
    assert config.source == "user"
    assert config.api_key == "sk-or-onboarding-user"


def test_embedder_fallback_no_api_key(monkeypatch):
    """role='embedder' → provider='ollama', base_url depuis OLLAMA_URL, api_key=None (pas de clé pour Ollama)."""
    monkeypatch.setenv("OLLAMA_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    with patch("services.tenant_llm_router.get_llm_config", return_value=None):
        config = TenantLLMRouter(user_id=7).get_config("embedder")
    assert config.source == "env"
    assert config.provider == "ollama"
    assert config.api_key is None
    assert config.base_url == "http://host.docker.internal:11434"
    assert config.model == "nomic-embed-text"
