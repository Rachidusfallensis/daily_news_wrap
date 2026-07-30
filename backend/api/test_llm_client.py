"""Tests for services/llm_client.py — generic per-provider completion dispatcher."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

_api_dir = os.path.join(os.path.dirname(__file__))
for p in [_api_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.llm_client import complete
from services.tenant_llm_router import LLMConfig


def _run(coro):
    return asyncio.run(coro)


def _mock_response(json_body, is_success=True):
    resp = MagicMock()
    resp.is_success = is_success
    resp.json.return_value = json_body
    resp.text = "error body"
    return resp


def test_complete_openrouter_success():
    config = LLMConfig(provider="openrouter", model="google/gemini-flash-1.5",
                        api_key="sk-or-x", base_url=None, source="user")
    resp = _mock_response({"choices": [{"message": {"content": "hello"}}]})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as mock_post:
        result = _run(complete(config, "system", "user msg"))
    assert result == "hello"
    url, kwargs = mock_post.call_args
    assert url[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-x"
    assert kwargs["headers"]["HTTP-Referer"] == "https://github.com/basira"


def test_complete_openai_success():
    config = LLMConfig(provider="openai", model="gpt-4o-mini",
                        api_key="sk-x", base_url=None, source="user")
    resp = _mock_response({"choices": [{"message": {"content": "hi"}}]})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as mock_post:
        result = _run(complete(config, "system", "user msg"))
    assert result == "hi"
    url, kwargs = mock_post.call_args
    assert url[0] == "https://api.openai.com/v1/chat/completions"
    assert "HTTP-Referer" not in kwargs["headers"]


def test_complete_ollama_success():
    config = LLMConfig(provider="ollama", model="mistral",
                        api_key=None, base_url="http://host.docker.internal:11434", source="user")
    resp = _mock_response({"message": {"content": "local reply"}})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as mock_post:
        result = _run(complete(config, "system", "user msg"))
    assert result == "local reply"
    url, _kwargs = mock_post.call_args
    assert url[0] == "http://host.docker.internal:11434/api/chat"


def test_complete_anthropic_success():
    config = LLMConfig(provider="anthropic", model="claude-3-haiku-20240307",
                        api_key="sk-ant-x", base_url=None, source="user")
    resp = _mock_response({"content": [{"text": "claude reply"}]})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as mock_post:
        result = _run(complete(config, "system", "user msg"))
    assert result == "claude reply"
    url, kwargs = mock_post.call_args
    assert url[0] == "https://api.anthropic.com/v1/messages"
    assert kwargs["headers"]["x-api-key"] == "sk-ant-x"
    assert kwargs["json"]["system"] == "system"


def test_complete_gemini_success():
    config = LLMConfig(provider="gemini", model="gemini-1.5-flash",
                        api_key="AIza-x", base_url=None, source="user")
    resp = _mock_response({"candidates": [{"content": {"parts": [{"text": "gemini reply"}]}}]})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as mock_post:
        result = _run(complete(config, "system", "user msg"))
    assert result == "gemini reply"
    url, _kwargs = mock_post.call_args
    assert "gemini-1.5-flash:generateContent?key=AIza-x" in url[0]


def test_complete_anthropic_missing_key_returns_none():
    config = LLMConfig(provider="anthropic", model="claude-3-haiku-20240307",
                        api_key=None, base_url=None, source="env")
    result = _run(complete(config, "system", "user msg"))
    assert result is None


def test_complete_unknown_provider_returns_none():
    config = LLMConfig(provider="does-not-exist", model="x", api_key="y", base_url=None, source="user")
    result = _run(complete(config, "system", "user msg"))
    assert result is None


def test_complete_never_raises_on_http_error():
    config = LLMConfig(provider="openrouter", model="google/gemini-flash-1.5",
                        api_key="sk-or-x", base_url=None, source="user")
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=Exception("boom"))):
        result = _run(complete(config, "system", "user msg"))
    assert result is None


def test_complete_never_raises_on_http_failure_status():
    config = LLMConfig(provider="openrouter", model="google/gemini-flash-1.5",
                        api_key="sk-or-x", base_url=None, source="user")
    resp = _mock_response({}, is_success=False)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
        result = _run(complete(config, "system", "user msg"))
    assert result is None
