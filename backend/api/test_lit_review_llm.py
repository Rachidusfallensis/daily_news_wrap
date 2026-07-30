"""Tests for lit_review_llm.py tenant routing (Story MT-LLM-gate).

lit_review_llm.py has no chromadb/DB dependency (httpx + structlog only), so
these run functionally on host — unlike test_literature_review.py's broader
Story 3.4 suite which needs the full API stack.
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

_api_dir = os.path.join(os.path.dirname(__file__))
for p in [_api_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from lit_review_llm import synthesize_cluster_json, synthesize_external_review_json

_VALID_JSON = json.dumps({
    "synthesis": "one paragraph",
    "comparison_table": [{"work": "X", "method": "Y", "dataset": "Z", "key_result": "W"}],
    "gaps": ["gap1"],
    "top_cite": "Some Paper",
})


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# synthesize_cluster_json — legacy path unchanged
# ---------------------------------------------------------------------------


def test_synthesize_cluster_json_no_user_id_uses_legacy_ladder():
    with patch("lit_review_llm._chat_uni", new=AsyncMock(return_value=None)), \
         patch("lit_review_llm._chat_ollama", new=AsyncMock(return_value=None)), \
         patch("lit_review_llm._chat_openrouter", new=AsyncMock(return_value=_VALID_JSON)) as mock_or:
        result = _run(synthesize_cluster_json("Cluster A", "papers block"))
    assert result["top_cite"] == "Some Paper"
    mock_or.assert_awaited_once()


# ---------------------------------------------------------------------------
# synthesize_cluster_json — tenant routing
# ---------------------------------------------------------------------------


def test_synthesize_cluster_json_user_id_routes_via_tenant_llm_router():
    fake_router_instance = MagicMock()
    fake_router_instance.get_config.return_value = MagicMock(provider="openrouter", model="m")

    with (
        patch("services.tenant_llm_router.TenantLLMRouter", lambda user_id: fake_router_instance),
        patch("services.llm_client.complete", new=AsyncMock(return_value=_VALID_JSON)) as mock_complete,
        patch("lit_review_llm._chat_uni", new=AsyncMock()) as mock_legacy,
    ):
        result = _run(synthesize_cluster_json("Cluster A", "papers block", user_id=42))

    assert result["top_cite"] == "Some Paper"
    mock_legacy.assert_not_awaited()
    fake_router_instance.get_config.assert_called_once_with("onboarding")
    mock_complete.assert_awaited_once()


def test_synthesize_cluster_json_all_tiers_fail_raises():
    with patch("lit_review_llm._chat_uni", new=AsyncMock(return_value=None)), \
         patch("lit_review_llm._chat_ollama", new=AsyncMock(return_value=None)), \
         patch("lit_review_llm._chat_openrouter", new=AsyncMock(return_value=None)):
        try:
            _run(synthesize_cluster_json("Cluster A", "papers block"))
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# synthesize_external_review_json — legacy + tenant routing
# ---------------------------------------------------------------------------


def test_synthesize_external_review_json_no_user_id_uses_legacy_ladder():
    with patch("lit_review_llm._chat_uni", new=AsyncMock(return_value=None)), \
         patch("lit_review_llm._chat_ollama", new=AsyncMock(return_value=_VALID_JSON)) as mock_ollama:
        result = _run(synthesize_external_review_json("topic", "paper block"))
    assert result["top_cite"] == "Some Paper"
    mock_ollama.assert_awaited_once()


def test_synthesize_external_review_json_user_id_routes_via_tenant_llm_router():
    fake_router_instance = MagicMock()
    fake_router_instance.get_config.return_value = MagicMock(provider="anthropic", model="claude-3-haiku")

    with (
        patch("services.tenant_llm_router.TenantLLMRouter", lambda user_id: fake_router_instance),
        patch("services.llm_client.complete", new=AsyncMock(return_value=_VALID_JSON)) as mock_complete,
        patch("lit_review_llm._chat_uni", new=AsyncMock()) as mock_legacy,
    ):
        result = _run(synthesize_external_review_json("topic", "paper block", user_id=7))

    assert result["top_cite"] == "Some Paper"
    mock_legacy.assert_not_awaited()
    fake_router_instance.get_config.assert_called_once_with("onboarding")
    mock_complete.assert_awaited_once()
