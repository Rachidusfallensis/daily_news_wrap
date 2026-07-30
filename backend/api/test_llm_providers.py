"""Tests for llm_providers.py verify_connection() (Epic 15, FR-MT-73)."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

_api_dir = os.path.join(os.path.dirname(__file__))
for p in [_api_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from llm_providers import verify_connection


def _run(coro):
    return asyncio.run(coro)


def test_verify_openrouter_calls_models_endpoint():
    with patch("llm_providers._get_ok", new=AsyncMock(return_value={"ok": True})) as mock_get:
        result = _run(verify_connection("openrouter", "sk-or-x"))
    assert result == {"ok": True}
    url, kwargs = mock_get.call_args
    assert url[0] == "https://openrouter.ai/api/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-x"


def test_verify_openai_calls_models_endpoint():
    with patch("llm_providers._get_ok", new=AsyncMock(return_value={"ok": True})) as mock_get:
        result = _run(verify_connection("openai", "sk-x"))
    assert result == {"ok": True}
    url, kwargs = mock_get.call_args
    assert url[0] == "https://api.openai.com/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-x"


def test_verify_ollama_calls_tags_endpoint():
    with patch("llm_providers._get_ok", new=AsyncMock(return_value={"ok": True})) as mock_get:
        result = _run(verify_connection("ollama", "", base_url="http://localhost:11434"))
    assert result == {"ok": True}
    url, _kwargs = mock_get.call_args
    assert url[0] == "http://localhost:11434/api/tags"


def test_verify_anthropic_calls_models_endpoint_with_x_api_key():
    with patch("llm_providers._get_ok", new=AsyncMock(return_value={"ok": True})) as mock_get:
        result = _run(verify_connection("anthropic", "sk-ant-x"))
    assert result == {"ok": True}
    url, kwargs = mock_get.call_args
    assert url[0] == "https://api.anthropic.com/v1/models"
    assert kwargs["headers"]["x-api-key"] == "sk-ant-x"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


def test_verify_gemini_calls_models_endpoint_with_key_param():
    with patch("llm_providers._get_ok", new=AsyncMock(return_value={"ok": True})) as mock_get:
        result = _run(verify_connection("gemini", "AIza-x"))
    assert result == {"ok": True}
    url, _kwargs = mock_get.call_args
    assert url[0] == "https://generativelanguage.googleapis.com/v1beta/models?key=AIza-x"


def test_verify_unknown_provider_returns_not_supported():
    result = _run(verify_connection("does-not-exist", "key"))
    assert result["ok"] is False
    assert "not supported" in result["error"].lower()
