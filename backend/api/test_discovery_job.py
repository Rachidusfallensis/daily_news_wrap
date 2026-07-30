"""Tests for Slice B — background discovery job.

Verifies:
- run_discovery_job status transitions: expanding → resolving → done
- SSE progress events broadcast per stage
- LLM failure → status='error', no persist, no exception raised
- run_discovery_job with keywords skips LLM expand
- POST /api/discovery/run returns 202 with run_id
- GET /api/discovery/run/{id} returns status
- GET /api/discovery/run/{id} with wrong user → 404
- Input-hash dedup: same thesis_text reuses completed run

Run inside Docker:
    docker compose exec api pytest test_discovery_job.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

os.environ.setdefault("AUTH_PASSWORD", "test-password-job")
os.environ.setdefault("DB_PATH", "/tmp/test_basira_job.db")

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/services")

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import text

from database import init_db, engine
from services import source_discovery
from sse import _sse_queues


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    # Clear discovery_runs between tests
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM discovery_runs"))
        conn.execute(text("DELETE FROM sources"))
        conn.execute(text("DELETE FROM user_source_subscriptions"))
        conn.execute(text("DELETE FROM tracked_venues"))
        conn.execute(text("DELETE FROM tracked_authors"))
        conn.commit()
    _sse_queues.clear()
    yield
    _sse_queues.clear()


def _insert_run(user_id: int, status: str = "pending", expand_input: str = "hash") -> int:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "INSERT INTO discovery_runs (user_id, expand_input, status, created_at) "
                "VALUES (:uid, :h, :s, datetime('now'))"
            ),
            {"uid": user_id, "h": expand_input, "s": status},
        )
        conn.commit()
        return result.lastrowid


def _get_run(run_id: int) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, pack_result_json FROM discovery_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
    if not row:
        return {}
    pack = None
    if row[1]:
        try:
            pack = json.loads(row[1])
        except Exception:
            pass
    return {"status": row[0], "pack": pack}


# ---------------------------------------------------------------------------
# Unit tests for run_discovery_job
# ---------------------------------------------------------------------------


def test_job_status_transitions_to_done():
    """Happy path: expand + resolve succeed → status = 'done'.

    run_discovery_job calls _resolve_all/_cap_candidates/_verify_all/
    _rank_and_group directly (not the resolve_verify_rank() wrapper) — mock
    those, not the wrapper, or this silently exercises the real network-calling
    pipeline instead of the mock.
    """
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)
    fake_candidate = source_discovery.DiscoveryCandidate(
        name="arXiv", provider="arxiv", relevance_score=1.0, verified=True,
    )

    with (
        patch.object(source_discovery, "expand", new=AsyncMock(return_value=source_discovery.ExpandResult(
            field_label="ML", concepts=["neural networks"], degraded=False
        ))),
        patch.object(source_discovery, "_resolve_all", new=AsyncMock(return_value=[fake_candidate])),
        patch.object(source_discovery, "_verify_all", new=AsyncMock(return_value=[fake_candidate])),
    ):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    result = _get_run(run_id)
    assert result["status"] == "done"
    assert result["pack"] is not None
    assert result["pack"]["sources"][0]["name"] == "arXiv"


def test_job_threads_user_id_into_expand():
    """Story MT-LLM-gate: run_discovery_job must pass user_id through to expand()
    so the LLM call resolves the tenant's own config, not the shared fallback."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)

    with (
        patch.object(source_discovery, "expand", new=AsyncMock(
            return_value=source_discovery.ExpandResult(field_label="ML", degraded=False)
        )) as mock_expand,
        patch.object(source_discovery, "_resolve_all", new=AsyncMock(return_value=[])),
    ):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    mock_expand.assert_awaited_once_with("ML thesis", user_id=1)


def test_job_status_error_on_expand_failure():
    """LLM failure during expand → status = 'error', no re-raise."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)

    with patch.object(source_discovery, "expand", new=AsyncMock(side_effect=RuntimeError("LLM down"))):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    result = _get_run(run_id)
    assert result["status"] == "error"
    assert result["pack"] is None


def test_job_status_error_on_resolve_failure():
    """Provider failure during resolve → status = 'error'."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)

    with (
        patch.object(source_discovery, "expand", new=AsyncMock(return_value=source_discovery.ExpandResult(
            field_label="ML", concepts=["ml"], degraded=False
        ))),
        patch.object(source_discovery, "_resolve_all", new=AsyncMock(side_effect=RuntimeError("providers down"))),
    ):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    result = _get_run(run_id)
    assert result["status"] == "error"


def test_job_with_keywords_skips_expand_llm():
    """When keywords provided, expand() should NOT be called."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)

    with (
        patch.object(source_discovery, "expand", new=AsyncMock(return_value=source_discovery.ExpandResult())) as mock_expand,
        patch.object(source_discovery, "_resolve_all", new=AsyncMock(return_value=[])),
    ):
        asyncio.run(run_discovery_job(
            run_id=run_id,
            user_id=1,
            thesis_text="ML thesis",
            keywords=["machine learning", "neural networks", "transformers"],
        ))

    mock_expand.assert_not_called()
    assert _get_run(run_id)["status"] == "done"


def test_job_broadcasts_sse_events():
    """SSE progress events should reach the user's queue."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_queues[1] = {"test_client": q}

    with (
        patch.object(source_discovery, "expand", new=AsyncMock(return_value=source_discovery.ExpandResult(
            field_label="ML", degraded=False
        ))),
        patch.object(source_discovery, "_resolve_all", new=AsyncMock(return_value=[])),
    ):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    messages = []
    while not q.empty():
        messages.append(q.get_nowait())

    event_types = [m["type"] for m in messages]
    assert "discovery:expanding" in event_types
    assert "discovery:resolving" in event_types
    assert "discovery:done" in event_types


def test_job_broadcasts_error_sse_event():
    """On failure, discovery:error event should be broadcast."""
    from services.source_discovery import run_discovery_job

    run_id = _insert_run(user_id=1)
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_queues[1] = {"test_client": q}

    with patch.object(source_discovery, "expand", new=AsyncMock(side_effect=RuntimeError("fail"))):
        asyncio.run(run_discovery_job(run_id=run_id, user_id=1, thesis_text="ML thesis"))

    messages = [q.get_nowait() for _ in range(q.qsize())]
    assert any(m["type"] == "discovery:error" for m in messages)


# ---------------------------------------------------------------------------
# HTTP endpoint tests (POST /api/discovery/run, GET /api/discovery/run/{id})
# ---------------------------------------------------------------------------


def _make_client():
    from main import app
    from auth import require_session

    def _fake_session():
        return {"id": 1, "email": "test@test.com", "org_id": None}

    app.dependency_overrides[require_session] = _fake_session
    client = TestClient(app, raise_server_exceptions=False)
    return client, app


def test_post_run_returns_202():
    client, app = _make_client()
    try:
        with (
            patch("routers.discovery.asyncio") as mock_asyncio,
            patch("routers.discovery.has_user_llm_config", return_value=True),
        ):
            mock_asyncio.create_task = MagicMock()
            resp = client.post("/api/discovery/run", json={"thesis_text": "A unique thesis ABC"})
        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data
        assert data["status"] in ("pending", "done")
    finally:
        app.dependency_overrides.clear()


def test_post_run_requires_llm_config():
    """Story MT-LLM-gate: no user_llm_configs row for 'onboarding' → 428, no task spawned."""
    client, app = _make_client()
    try:
        with (
            patch("routers.discovery.asyncio") as mock_asyncio,
            patch("routers.discovery.has_user_llm_config", return_value=False),
        ):
            mock_asyncio.create_task = MagicMock()
            resp = client.post("/api/discovery/run", json={"thesis_text": "Some thesis"})
        assert resp.status_code == 428
        mock_asyncio.create_task.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_get_run_returns_status():
    client, app = _make_client()
    try:
        run_id = _insert_run(user_id=1, status="expanding")
        resp = client.get(f"/api/discovery/run/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "expanding"
    finally:
        app.dependency_overrides.clear()


def test_get_run_wrong_user_returns_404():
    from auth import require_session

    client, app = _make_client()

    def _other_user():
        return {"id": 999, "email": "other@test.com", "org_id": None}

    try:
        run_id = _insert_run(user_id=1, status="done")
        app.dependency_overrides[require_session] = _other_user
        resp = client.get(f"/api/discovery/run/{run_id}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_post_run_dedup_returns_existing_completed_run():
    """Same thesis_text → same input hash → existing done run returned, no new task."""
    client, app = _make_client()
    try:
        thesis = "Dedup thesis for testing uniqueness"
        sanitized = source_discovery.sanitize(thesis)
        import hashlib
        input_hash = hashlib.sha256(sanitized.encode()).hexdigest()
        run_id = _insert_run(user_id=1, status="done", expand_input=input_hash)

        with (
            patch("routers.discovery.asyncio") as mock_asyncio,
            patch("routers.discovery.has_user_llm_config", return_value=True),
        ):
            mock_asyncio.create_task = MagicMock()
            resp = client.post("/api/discovery/run", json={"thesis_text": thesis})

        assert resp.status_code == 202
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "done"
        mock_asyncio.create_task.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_get_run_done_includes_pack():
    """Completed run with pack_result_json → pack field populated."""
    client, app = _make_client()
    try:
        run_id = _insert_run(user_id=1, status="done")
        pack_data = {"sources": [{"name": "arXiv", "provider": "arxiv", "verified": True, "query_json": {}, "provenance_url": "", "label": "", "unverifiable": False}], "venues": [], "authors": []}
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE discovery_runs SET pack_result_json = :p WHERE id = :id"),
                {"p": json.dumps(pack_data), "id": run_id},
            )
            conn.commit()

        resp = client.get(f"/api/discovery/run/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pack"] is not None
        assert data["pack"]["sources"][0]["name"] == "arXiv"
    finally:
        app.dependency_overrides.clear()
