"""
TenantLLMRouter — resolves the right LLM config for a (user_id, role) pair.

Resolution chain (FR-MT-75):
  1. user_llm_configs DB row for (user_id, role)
  2. org_llm_defaults (future Epic 16 — placeholder here)
  3. Environment variables (backward compat, NFR-T13)

ISOLATION RULE (FR-MT-76, NFR-T1):
  user_id comes ONLY from require_session dependency.
  Never from URL param, query string, or request body.

Cache: per (user_id, role), module-level dict, invalidated on config update.
Pattern: mirrors OpenWorker ProviderRouter (coworker/providers/router.py)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional

import structlog

from database import SessionLocal, get_llm_config
from llm_crypto import LLMCryptoError, decrypt_key

logger = structlog.get_logger().bind(service="tenant_llm_router")

# ── Fallback env var mapping per role ────────────────────────────────────────
# Maps functional role → (provider_env, model_env, base_url_env)
_ENV_FALLBACK: dict[str, tuple[str, str, str]] = {
    "scorer":     ("OPENROUTER_API_KEY", "SCORER_MODEL",        "OPENROUTER_BASE_URL"),
    "embedder":   ("OLLAMA_URL",         "OLLAMA_EMBED_MODEL",  ""),
    "review":     ("OPENROUTER_API_KEY", "REVIEW_MODEL",        "OPENROUTER_BASE_URL"),
    "ask":        ("OPENROUTER_API_KEY", "ASK_MODEL",           "OPENROUTER_BASE_URL"),
    "onboarding": ("OPENROUTER_API_KEY", "SCORER_MODEL",        "OPENROUTER_BASE_URL"),
}

_DEFAULT_MODELS: dict[str, str] = {
    "scorer":     "google/gemini-flash-1.5",
    "embedder":   "nomic-embed-text",
    "review":     "google/gemini-flash-1.5",
    "ask":        "google/gemini-flash-1.5",
    "onboarding": "google/gemini-flash-1.5",
}


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: Optional[str]   # decrypted at resolution time, None for Ollama
    base_url: Optional[str]
    source: str              # "user" | "org" | "env"


# Module-level cache (shared across requests)
_cache: dict[tuple[int, str], LLMConfig] = {}
_lock = threading.Lock()


def has_user_llm_config(user_id: int, role: str = "onboarding") -> bool:
    """True iff a real `user_llm_configs` row exists for (user_id, role).

    Used to gate onboarding LLM calls (bootstrap/discovery) — deliberately
    checks the DB row directly rather than resolving through the router,
    since the router's env-var fallback tier must stay available for
    self-hosted/local-dev use without turning that fallback into an implicit
    "pass" for the multi-tenant SaaS gate.
    """
    db = SessionLocal()
    try:
        return get_llm_config(db, user_id, role) is not None
    finally:
        db.close()


class TenantLLMRouter:
    """
    Instantiate once per request with user_id from require_session.
    NEVER pass user_id from URL params or request body.
    """

    def __init__(self, user_id: int, org_id: Optional[int] = None) -> None:
        self._user_id = user_id
        self._org_id = org_id

    def get_config(self, role: str) -> LLMConfig:
        """Resolve LLM config for (self._user_id, role). Uses cache."""
        cache_key = (self._user_id, role)
        with _lock:
            if cache_key in _cache:
                return _cache[cache_key]

        config = self._resolve(role)

        with _lock:
            _cache[cache_key] = config

        return config

    @staticmethod
    def invalidate(user_id: Optional[int] = None) -> None:
        """Drop cache for user_id (or all users if None)."""
        with _lock:
            if user_id is None:
                _cache.clear()
            else:
                for key in list(_cache):
                    if key[0] == user_id:
                        del _cache[key]

    # ── Private resolution ────────────────────────────────────────────────

    def _resolve(self, role: str) -> LLMConfig:
        # 1. User DB config
        config = self._from_db_user(role)
        if config:
            return config
        # 2. Org DB config (Epic 16 — not yet implemented)
        # config = self._from_db_org(role)
        # if config:
        #     return config
        # 3. Env vars fallback
        return self._from_env(role)

    def _from_db_user(self, role: str) -> Optional[LLMConfig]:
        db = SessionLocal()
        try:
            row = get_llm_config(db, self._user_id, role)
            if not row:
                return None
            api_key: Optional[str] = None
            if row.api_key_enc:
                try:
                    api_key = decrypt_key(row.api_key_enc)
                except LLMCryptoError as e:
                    logger.warning("llm_key_decrypt_failed",
                                   user_id=self._user_id, role=role, error=str(e))
                    return None  # fall through to next tier
            return LLMConfig(
                provider=row.provider,
                model=row.model,
                api_key=api_key,
                base_url=row.base_url,
                source="user",
            )
        except Exception as e:
            logger.warning("llm_config_db_error",
                           user_id=self._user_id, role=role, error=str(e))
            return None
        finally:
            db.close()

    def _from_env(self, role: str) -> LLMConfig:
        key_var, model_var, url_var = _ENV_FALLBACK.get(
            role, ("OPENROUTER_API_KEY", "SCORER_MODEL", "OPENROUTER_BASE_URL")
        )
        # For embedder/Ollama the "key" is actually the base URL
        if role == "embedder":
            return LLMConfig(
                provider="ollama",
                model=os.getenv(model_var, _DEFAULT_MODELS[role]),
                api_key=None,
                base_url=os.getenv(key_var, "http://host.docker.internal:11434"),
                source="env",
            )
        return LLMConfig(
            provider="openrouter",
            model=os.getenv(model_var, _DEFAULT_MODELS.get(role, "google/gemini-flash-1.5")),
            api_key=os.getenv(key_var) or None,
            base_url=os.getenv(url_var) or None,
            source="env",
        )
