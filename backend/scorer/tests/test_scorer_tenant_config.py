"""Tests for scorer.py tenant-LLM-config routing (Story MT-LLM-gate).

Verifies:
- _get_tenant_llm_config() hits the internal endpoint, returns None on failure
- _score_with_tenant_config() dispatches per provider, never raises
- score_article()'s Tier 0 is gated by SCORER_TENANT_ROUTING_ENABLED (default off)
  and by tenant_cfg["source"] == "user" (never silently uses the env fallback)

Run inside Docker (or locally against backend/api/.venv, which has the same
fastapi/httpx/pydantic deps as scorer's own requirements.txt):
    docker-compose exec api python -m pytest backend/scorer/tests/test_scorer_tenant_config.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SCORER_DIR = Path(__file__).parent.parent
if str(SCORER_DIR) not in sys.path:
    sys.path.insert(0, str(SCORER_DIR))

import scorer  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _mock_response(json_body, is_success=True):
    resp = MagicMock()
    resp.is_success = is_success
    resp.json.return_value = json_body
    resp.text = "error body"
    return resp


VALID_SCORE_JSON = {
    "score": 8.5,
    "tags": ["nlp"],
    "summary_bullets": ["a bullet"],
    "reason": "solid paper",
}


# ---------------------------------------------------------------------------
# _get_tenant_llm_config
# ---------------------------------------------------------------------------


def test_get_tenant_llm_config_success():
    resp = _mock_response({"provider": "openrouter", "model": "m", "api_key": "sk-x",
                            "base_url": None, "source": "user"})
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    result = _run(scorer._get_tenant_llm_config(client, user_id=1, role="scorer"))
    assert result["provider"] == "openrouter"
    assert result["source"] == "user"
    client.get.assert_awaited_once()
    args, kwargs = client.get.call_args
    assert args[0] == f"{scorer.API_BASE}/api/internal/users/1/llm-config"
    assert kwargs["params"] == {"role": "scorer"}


def test_get_tenant_llm_config_never_raises_on_failure():
    client = MagicMock()
    client.get = AsyncMock(side_effect=Exception("network down"))
    result = _run(scorer._get_tenant_llm_config(client, user_id=1))
    assert result is None


def test_get_tenant_llm_config_none_on_http_failure():
    resp = _mock_response({}, is_success=False)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    result = _run(scorer._get_tenant_llm_config(client, user_id=1))
    assert result is None


# ---------------------------------------------------------------------------
# _score_with_tenant_config — per-provider dispatch
# ---------------------------------------------------------------------------


def test_score_with_tenant_config_openrouter():
    tenant_cfg = {"provider": "openrouter", "model": "m", "api_key": "sk-or-x", "base_url": None}
    resp = _mock_response({"choices": [{"message": {"content": json.dumps(VALID_SCORE_JSON)}}]})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is not None
    assert result.score == 8.5


def test_score_with_tenant_config_ollama():
    tenant_cfg = {"provider": "ollama", "model": "mistral", "api_key": None,
                  "base_url": "http://host.docker.internal:11434"}
    resp = _mock_response({"message": {"content": json.dumps(VALID_SCORE_JSON)}})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is not None
    assert result.score == 8.5


def test_score_with_tenant_config_anthropic():
    tenant_cfg = {"provider": "anthropic", "model": "claude-3-haiku", "api_key": "sk-ant-x", "base_url": None}
    resp = _mock_response({"content": [{"text": json.dumps(VALID_SCORE_JSON)}]})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is not None
    assert result.score == 8.5


def test_score_with_tenant_config_gemini():
    tenant_cfg = {"provider": "gemini", "model": "gemini-1.5-flash", "api_key": "AIza-x", "base_url": None}
    resp = _mock_response({"candidates": [{"content": {"parts": [{"text": json.dumps(VALID_SCORE_JSON)}]}}]})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is not None
    assert result.score == 8.5


def test_score_with_tenant_config_anthropic_missing_key_returns_none():
    tenant_cfg = {"provider": "anthropic", "model": "claude-3-haiku", "api_key": None, "base_url": None}
    client = MagicMock()
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is None


def test_score_with_tenant_config_unknown_provider_returns_none():
    tenant_cfg = {"provider": "does-not-exist", "model": "m", "api_key": "x", "base_url": None}
    client = MagicMock()
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is None


def test_score_with_tenant_config_never_raises():
    tenant_cfg = {"provider": "openrouter", "model": "m", "api_key": "sk-x", "base_url": None}
    client = MagicMock()
    client.post = AsyncMock(side_effect=Exception("boom"))
    result = _run(scorer._score_with_tenant_config(client, tenant_cfg, "user msg", "system", None))
    assert result is None


# ---------------------------------------------------------------------------
# score_article — Tier 0 gating (flag + source=="user")
# ---------------------------------------------------------------------------


def _score_request(user_id=1):
    return scorer.ScoreRequest(
        article_id=1, title="Some Paper", content_text="content here", user_id=user_id,
    )


def test_tier0_skipped_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(scorer, "SCORER_TENANT_ROUTING_ENABLED", False)
    with (
        patch.object(scorer, "_get_tenant_llm_config", new=AsyncMock()) as mock_get_cfg,
        patch.object(scorer, "score_with_uni_server", new=AsyncMock(return_value=None)),
        patch.object(scorer, "score_with_openrouter", new=AsyncMock(return_value=None)),
        patch.object(scorer, "score_with_ollama", new=AsyncMock(return_value=scorer.ScoreResult(score=5.0))),
        patch.object(scorer, "build_preference_block", new=AsyncMock(return_value="")),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_mock_response({"status": "ok"}))),
    ):
        _run(scorer.score_article(_score_request()))
    mock_get_cfg.assert_not_awaited()


def test_tier0_skipped_when_source_is_env(monkeypatch):
    """Flag on, but tenant has no real config row (source=='env') → must NOT use it."""
    monkeypatch.setattr(scorer, "SCORER_TENANT_ROUTING_ENABLED", True)
    with (
        patch.object(scorer, "_get_tenant_llm_config", new=AsyncMock(
            return_value={"provider": "openrouter", "model": "m", "api_key": "shared-key",
                          "base_url": None, "source": "env"})),
        patch.object(scorer, "_score_with_tenant_config", new=AsyncMock()) as mock_tenant_score,
        patch.object(scorer, "score_with_uni_server", new=AsyncMock(return_value=None)),
        patch.object(scorer, "score_with_openrouter", new=AsyncMock(return_value=None)),
        patch.object(scorer, "score_with_ollama", new=AsyncMock(return_value=scorer.ScoreResult(score=5.0))),
        patch.object(scorer, "build_preference_block", new=AsyncMock(return_value="")),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_mock_response({"status": "ok"}))),
    ):
        _run(scorer.score_article(_score_request()))
    mock_tenant_score.assert_not_awaited()


def test_tier0_used_when_flag_on_and_source_is_user(monkeypatch):
    monkeypatch.setattr(scorer, "SCORER_TENANT_ROUTING_ENABLED", True)
    with (
        patch.object(scorer, "_get_tenant_llm_config", new=AsyncMock(
            return_value={"provider": "anthropic", "model": "claude-3-haiku", "api_key": "sk-ant-x",
                          "base_url": None, "source": "user"})),
        patch.object(scorer, "_score_with_tenant_config", new=AsyncMock(
            return_value=scorer.ScoreResult(score=9.0))) as mock_tenant_score,
        patch.object(scorer, "score_with_uni_server", new=AsyncMock()) as mock_uni,
        patch.object(scorer, "score_with_openrouter", new=AsyncMock()) as mock_or,
        patch.object(scorer, "score_with_ollama", new=AsyncMock()) as mock_ollama,
        patch.object(scorer, "build_preference_block", new=AsyncMock(return_value="")),
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_mock_response({"status": "ok"}))),
    ):
        _run(scorer.score_article(_score_request()))
    mock_tenant_score.assert_awaited_once()
    mock_uni.assert_not_awaited()
    mock_or.assert_not_awaited()
    mock_ollama.assert_not_awaited()
