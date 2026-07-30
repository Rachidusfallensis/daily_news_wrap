"""Tests for Story 13-5 — Discovery Apply (idempotent persist).

Verifies:
- POST /api/discovery/apply persists sources, venues, authors (AC1).
- Applying the same pack twice is idempotent (AC2).
- Existing venues are not modified (AC3).
- Discovery runs status tracking (AC4).
- Auth guard (isolation).
"""

import json
import os
import sys

os.environ["DB_PATH"] = "/tmp/test_discovery_apply.db"
os.environ["AUTH_PASSWORD"] = "testpass"
os.environ["AUTH_EMAIL"] = "admin@basira.local"
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")

_api_dir = os.path.join(os.path.dirname(__file__))
_extractor_dir = os.path.join(_api_dir, "..", "extractor")
for p in [_api_dir, _extractor_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from database import Base, SessionLocal, engine, init_db
from auth import create_session

from fastapi import FastAPI

from routers.discovery import router as discovery_router

app = FastAPI()
app.include_router(discovery_router)

from fastapi.testclient import TestClient


def _reset_db():
    from sqlalchemy import text as _text
    with engine.connect() as conn:
        conn.execute(_text("PRAGMA foreign_keys = OFF"))
        conn.commit()
        Base.metadata.drop_all(bind=conn)
        conn.execute(_text("PRAGMA foreign_keys = ON"))
        conn.commit()
    init_db()


def _seed_user(user_id: int):
    from datetime import datetime, timezone
    from sqlalchemy import text
    from database import engine as _eng
    with _eng.connect() as c:
        existing = c.execute(text("SELECT id FROM users WHERE id=:uid"), {"uid": user_id}).fetchone()
        if not existing:
            c.execute(
                text("INSERT INTO users (id, email, password_hash, display_name, role, onboarding_done, created_at) VALUES (:id, :email, '', :name, 'user', 1, :now)"),
                {"id": user_id, "email": f"user{user_id}@test.local", "name": f"User{user_id}", "now": datetime.now(timezone.utc)},
            )
            c.commit()


def _auth_headers(client, user_id: int = 1) -> dict:
    _seed_user(user_id)
    session = create_session(user_id=user_id, remember=False, user_agent="test")
    return {"Cookie": f"basira_sid={session}"}


def _get_client():
    return TestClient(app)


_ITEM_SOURCE = {
    "name": "ACL Anthology",
    "provider": "openalex",
    "query_json": {"openalex_id": "https://openalex.org/S123456"},
    "provenance_url": "https://example.com/acl",
    "verified": True,
    "label": "journal",
    "unverifiable": False,
}

_ITEM_VENUE = {
    "name": "ACL",
    "provider": "openalex",
    "query_json": {},
    "provenance_url": "",
    "verified": False,
    "label": "venue",
    "unverifiable": False,
}

_ITEM_AUTHOR = {
    "name": "Jane Doe",
    "provider": "openalex",
    "query_json": {"openalex_id": "https://openalex.org/A98765"},
    "provenance_url": "",
    "verified": False,
    "label": "author",
    "unverifiable": False,
}

_ITEM_AUTHOR_NO_ID = {
    "name": "Unknown Researcher",
    "provider": "openalex",
    "query_json": {},
    "provenance_url": "",
    "verified": False,
    "label": "author",
    "unverifiable": False,
}


def _count_rows(table: str) -> int:
    from sqlalchemy import text
    with engine.connect() as c:
        row = c.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
        return row[0] if row else 0


def _rows_exist(table: str, **filters) -> bool:
    from sqlalchemy import text
    clauses = " AND ".join(f"{k} = :{k}" for k in filters)
    with engine.connect() as c:
        row = c.execute(text(f"SELECT 1 FROM {table} WHERE {clauses} LIMIT 1"), filters).fetchone()
        return row is not None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_apply_persists_all():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    resp = client.post("/api/discovery/apply", json={
        "sources": [_ITEM_SOURCE],
        "venues": [_ITEM_VENUE],
        "authors": [_ITEM_AUTHOR],
    }, headers=headers)
    assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["applied"] is True
    assert body["counts"]["sources"] >= 1
    assert body["counts"]["venues"] >= 1
    assert body["counts"]["authors"] >= 1

    assert _count_rows("sources") >= 1
    assert _count_rows("user_source_subscriptions") >= 1
    assert _count_rows("tracked_venues") >= 1
    assert _count_rows("tracked_authors") >= 1


def test_apply_idempotent():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    payload = {
        "sources": [_ITEM_SOURCE],
        "venues": [_ITEM_VENUE],
        "authors": [_ITEM_AUTHOR],
    }

    resp1 = client.post("/api/discovery/apply", json=payload, headers=headers)
    assert resp1.status_code == 200
    counts1 = resp1.json()["counts"]

    resp2 = client.post("/api/discovery/apply", json=payload, headers=headers)
    assert resp2.status_code == 200
    counts2 = resp2.json()["counts"]

    # Second apply should not create duplicate sources
    sources_before = _count_rows("sources")
    subs_before = _count_rows("user_source_subscriptions")
    venues_before = _count_rows("tracked_venues")
    authors_before = _count_rows("tracked_authors")

    resp3 = client.post("/api/discovery/apply", json=payload, headers=headers)
    assert resp3.status_code == 200

    assert _count_rows("sources") == sources_before
    assert _count_rows("user_source_subscriptions") == subs_before
    assert _count_rows("tracked_venues") == venues_before
    assert _count_rows("tracked_authors") == authors_before


def test_existing_venue_unchanged():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    payload = {"sources": [], "venues": [_ITEM_VENUE], "authors": []}
    client.post("/api/discovery/apply", json=payload, headers=headers)

    venues_before = _count_rows("tracked_venues")

    client.post("/api/discovery/apply", json=payload, headers=headers)

    assert _count_rows("tracked_venues") == venues_before


def test_existing_author_unchanged():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    payload = {"sources": [], "venues": [], "authors": [_ITEM_AUTHOR]}
    client.post("/api/discovery/apply", json=payload, headers=headers)

    authors_before = _count_rows("tracked_authors")

    client.post("/api/discovery/apply", json=payload, headers=headers)

    assert _count_rows("tracked_authors") == authors_before


def test_author_no_openalex_id():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    payload = {"sources": [], "venues": [], "authors": [_ITEM_AUTHOR_NO_ID]}
    resp = client.post("/api/discovery/apply", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["counts"]["authors"] >= 1
    assert _rows_exist("tracked_authors", name="Unknown Researcher")


def test_apply_requires_auth():
    _reset_db()
    client = _get_client()
    resp = client.post("/api/discovery/apply", json={
        "sources": [], "venues": [], "authors": [],
    })
    assert resp.status_code in (401, 403), f"Expected 401/403 got {resp.status_code}"


def test_apply_empty_pack():
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)

    resp = client.post("/api/discovery/apply", json={
        "sources": [], "venues": [], "authors": [],
    }, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True


def _insert_discovery_run(user_id: int, status: str = "done", pack_json: str | None = None) -> int:
    """Helper: insert a discovery_runs row and return its id."""
    import json as _json
    from datetime import datetime, timezone
    from sqlalchemy import text
    if pack_json is None:
        pack_json = _json.dumps({"sources": [_ITEM_SOURCE], "venues": [_ITEM_VENUE], "authors": [_ITEM_AUTHOR]})
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "INSERT INTO discovery_runs (user_id, expand_input, status, pack_result_json, created_at) "
                "VALUES (:uid, :h, :status, :pack, datetime('now'))"
            ),
            {"uid": user_id, "h": "testhash", "status": status, "pack": pack_json},
        )
        conn.commit()
        return result.lastrowid


def test_run_apply_sets_status_applied():
    """AC4: POST /api/discovery/run/{id}/apply marks run as status=applied + applied_at."""
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)
    run_id = _insert_discovery_run(user_id=1)

    resp = client.post(f"/api/discovery/run/{run_id}/apply", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True

    with engine.connect() as conn:
        from sqlalchemy import text
        row = conn.execute(
            text("SELECT status, applied_at FROM discovery_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
    assert row is not None
    assert row[0] == "applied", f"Expected 'applied', got '{row[0]}'"
    assert row[1] is not None, "applied_at should be set"


def test_run_apply_idempotent():
    """Applying the same run twice returns counts={} on second call."""
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)
    run_id = _insert_discovery_run(user_id=1)

    client.post(f"/api/discovery/run/{run_id}/apply", headers=headers)
    resp2 = client.post(f"/api/discovery/run/{run_id}/apply", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["counts"] == {}


def test_run_apply_ownership_isolation():
    """User B cannot apply User A's run (NFR-T1)."""
    _reset_db()
    client = _get_client()
    headers_a = _auth_headers(client, user_id=1)
    run_id = _insert_discovery_run(user_id=1)

    headers_b = _auth_headers(client, user_id=2)
    resp = client.post(f"/api/discovery/run/{run_id}/apply", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


def test_run_apply_wrong_status():
    """Applying a pending run returns 409."""
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)
    run_id = _insert_discovery_run(user_id=1, status="pending")

    resp = client.post(f"/api/discovery/run/{run_id}/apply", headers=headers)
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"


def test_run_apply_with_curated_items():
    """Apply with explicit body applies only the provided items (no extra venues inserted)."""
    _reset_db()
    client = _get_client()
    headers = _auth_headers(client)
    run_id = _insert_discovery_run(user_id=1)

    # Capture venue count before apply
    venues_before = _count_rows("tracked_venues")

    resp = client.post(
        f"/api/discovery/run/{run_id}/apply",
        json={"sources": [_ITEM_SOURCE], "venues": [], "authors": []},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True

    # No extra venues should have been inserted (we passed empty venues in the body)
    venues_after = _count_rows("tracked_venues")
    assert venues_after == venues_before, (
        f"Expected venue count to stay at {venues_before}, got {venues_after}"
    )


def run_tests():
    tests = [
        ("apply_persists_all", test_apply_persists_all),
        ("apply_idempotent", test_apply_idempotent),
        ("existing_venue_unchanged", test_existing_venue_unchanged),
        ("existing_author_unchanged", test_existing_author_unchanged),
        ("author_no_openalex_id", test_author_no_openalex_id),
        ("apply_requires_auth", test_apply_requires_auth),
        ("apply_empty_pack", test_apply_empty_pack),
        ("run_apply_sets_status_applied", test_run_apply_sets_status_applied),
        ("run_apply_idempotent", test_run_apply_idempotent),
        ("run_apply_ownership_isolation", test_run_apply_ownership_isolation),
        ("run_apply_wrong_status", test_run_apply_wrong_status),
        ("run_apply_with_curated_items", test_run_apply_with_curated_items),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  \u2705  {name}")
            passed += 1
        except Exception as e:
            print(f"  \u274c  {name}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"  {passed}/{passed + failed} passed")
    if failed:
        print(f"  \u274c  {failed} FAILED")
    else:
        print(f"  \u2705  ALL PASSED")


if __name__ == "__main__":
    run_tests()
