"""
LLM Provider Descriptors for Baṣīra (Epic 15, FR-MT-70–74).

Differences from OpenWorker:
  - No ProviderClient abstraction (Baṣīra uses raw httpx)
  - Descriptors drive UI form rendering only
  - verify_connection() does one cheap read-only call per provider
  - detect_provider() mirrors OpenWorker's detect_provider()

Pattern: ProviderDescriptor + ProviderField dataclasses (frozen)
         → to_dict() → sent to frontend as JSON → form rendered dynamically
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger().bind(service="llm_providers")

_VERIFY_TIMEOUT = 10.0


@dataclass(frozen=True)
class ProviderField:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""
    default: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class LLMProviderDescriptor:
    name: str       # "openrouter" | "openai" | "ollama" | "anthropic" | "gemini"
    title: str
    needs_key: bool
    fields: list[ProviderField]
    recommended_model: Optional[str] = None
    env_key: Optional[str] = None
    blurb: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "needs_key": self.needs_key,
            "fields": [f.to_dict() for f in self.fields],
            "recommended_model": self.recommended_model,
            "blurb": self.blurb,
        }


DESCRIPTORS: list[LLMProviderDescriptor] = [
    LLMProviderDescriptor(
        name="openrouter",
        title="OpenRouter",
        needs_key=True,
        fields=[
            ProviderField("api_key", "OpenRouter API key", secret=True, placeholder="sk-or-…"),
            ProviderField("base_url", "Endpoint (optionnel)", required=False,
                         default="https://openrouter.ai/api/v1"),
        ],
        recommended_model="google/gemini-flash-1.5",
        env_key="OPENROUTER_API_KEY",
        blurb="Accès à tous les grands modèles via une seule clé.",
    ),
    LLMProviderDescriptor(
        name="openai",
        title="OpenAI",
        needs_key=True,
        fields=[
            ProviderField("api_key", "OpenAI API key", secret=True, placeholder="sk-…"),
        ],
        recommended_model="gpt-4o-mini",
        env_key="OPENAI_API_KEY",
    ),
    LLMProviderDescriptor(
        name="anthropic",
        title="Claude (Anthropic)",
        needs_key=True,
        fields=[
            ProviderField("api_key", "Anthropic API key", secret=True, placeholder="sk-ant-…"),
        ],
        recommended_model="claude-3-haiku-20240307",
        env_key="ANTHROPIC_API_KEY",
    ),
    LLMProviderDescriptor(
        name="gemini",
        title="Gemini (Google)",
        needs_key=True,
        fields=[
            ProviderField("api_key", "Gemini API key", secret=True, placeholder="AIza…"),
        ],
        recommended_model="gemini-1.5-flash",
        env_key="GEMINI_API_KEY",
    ),
    LLMProviderDescriptor(
        name="ollama",
        title="Ollama (modèles locaux)",
        needs_key=False,
        fields=[
            ProviderField("base_url", "URL du serveur Ollama", required=False,
                         placeholder="http://host.docker.internal:11434",
                         help="URL où `ollama serve` écoute."),
        ],
        recommended_model="llama3.2:3b",
        blurb="Modèles locaux — aucune clé requise, zéro coût.",
    ),
]

_BY_NAME = {d.name: d for d in DESCRIPTORS}


def get_descriptor(name: str) -> Optional[LLMProviderDescriptor]:
    return _BY_NAME.get(name)


def detect_provider(api_key: str) -> Optional[str]:
    """Best-effort provider detection from API key shape (mirrors OpenWorker)."""
    key = (api_key or "").strip()
    if not key:
        return None
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("sk-or-"):
        return "openrouter"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith(("sk-", "sk_")):
        return "openai"
    return None


def _guard_base_url(url: str) -> None:
    """Validate a user-supplied base_url override before calling it (SSRF guard).

    Only applied to openrouter/openai overrides: their default endpoints are
    hardcoded public HTTPS APIs, so the only attacker-reachable surface is a
    user-supplied override. Ollama's base_url is intentionally NOT guarded —
    it exists specifically to reach a private/self-hosted endpoint (typically
    http://host.docker.internal:11434), exactly like every other Ollama call
    site in this codebase (embedder.py, scorer.py). net_guard's HTTPS-only /
    no-private-IP policy would make local Ollama unusable if applied to it.
    """
    from net_guard import SSRFBlockedError, check_url
    try:
        check_url(url)
    except SSRFBlockedError as e:
        raise ValueError(f"Blocked base_url: {e}")


async def _get_ok(url: str, headers: Optional[dict] = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT) as client:
            resp = await client.get(url, headers=headers or {})
        if resp.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


async def verify_connection(provider: str, api_key: str, base_url: str = "") -> dict:
    """One cheap read-only call to verify credentials. Returns {"ok": bool, "error"?: str}."""
    try:
        if provider == "openrouter":
            url = (base_url or "https://openrouter.ai/api/v1").rstrip("/") + "/models"
            if base_url:
                _guard_base_url(url)
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            return await _get_ok(url, headers=headers)

        if provider == "openai":
            url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/models"
            if base_url:
                _guard_base_url(url)
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            return await _get_ok(url, headers=headers)

        if provider == "ollama":
            url = (base_url or "http://host.docker.internal:11434").rstrip("/") + "/api/tags"
            return await _get_ok(url)

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/models"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            return await _get_ok(url, headers=headers)

        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            return await _get_ok(url)

        return {"ok": False, "error": f"Verification not supported for provider '{provider}'"}
    except Exception as e:
        logger.warning("llm_verify_failed", provider=provider, error=str(e))
        return {"ok": False, "error": str(e)}
