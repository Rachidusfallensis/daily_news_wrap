"""Discovery API router — EXPAND + RESOLVE + background RUN endpoints.

Exposes the source_discovery service functions behind authenticated endpoints
with per-user rate limiting (expand only — resolve is stateless data transform).

FR-MT-59–62: HTTP layer wrapping expand + resolve_verify_rank services.
Story 15.1: POST /api/discovery/run + GET /api/discovery/run/{id} for
non-blocking background job orchestration.
"""

import asyncio
import hashlib
import json
import os
import time
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import require_session
from services import source_discovery

router = APIRouter(prefix="/api/discovery", tags=["discovery"])
_auth = Depends(require_session)
logger = structlog.get_logger().bind(service="discovery")

# ---------------------------------------------------------------------------
# Rate limiter — per-user, in-memory (identical pattern to profile router)
# ---------------------------------------------------------------------------

EXPAND_RATE_LIMIT = int(os.getenv("EXPAND_RATE_LIMIT", "10"))
EXPAND_RATE_WINDOW_SECONDS = int(os.getenv("EXPAND_RATE_WINDOW_SECONDS", "3600"))
_expand_calls: dict[int, list[float]] = {}


def _check_expand_rate_limit(user_id: int) -> Optional[int]:
    now = time.monotonic()
    window = EXPAND_RATE_WINDOW_SECONDS
    history = _expand_calls.setdefault(user_id, [])
    cutoff = now - window
    history[:] = [t for t in history if t > cutoff]
    if len(history) >= EXPAND_RATE_LIMIT:
        retry_after = int(window - (now - history[0])) + 1
        return max(retry_after, 1)
    history.append(now)
    return None


def _reset_expand_rate_limits() -> None:
    _expand_calls.clear()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ExpandRequest(BaseModel):
    thesis_text: str


class ResolveRequest(BaseModel):
    expand_result: dict


# ---------------------------------------------------------------------------
# POST /api/discovery/expand
# ---------------------------------------------------------------------------


@router.post("/expand", response_model=source_discovery.ExpandResult)
async def post_expand(
    body: ExpandRequest,
    response: Response,
    current_user: dict = Depends(require_session),
):
    user_id = current_user["id"]
    retry_after = _check_expand_rate_limit(user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Expand rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    result = await source_discovery.expand(body.thesis_text)
    logger.info(
        "expand_endpoint",
        user_id=user_id,
        degraded=result.degraded,
        concepts=len(result.concepts),
    )
    return result


# ---------------------------------------------------------------------------
# POST /api/discovery/resolve
# ---------------------------------------------------------------------------


@router.post("/resolve", response_model=source_discovery.DiscoveryPack)
async def post_resolve(
    body: ResolveRequest,
    current_user: dict = Depends(require_session),
):
    user_id = current_user["id"]
    try:
        expand_result = source_discovery.ExpandResult.model_validate(body.expand_result)
        pack = await source_discovery.resolve_verify_rank(expand_result)
        logger.info(
            "resolve_endpoint",
            user_id=user_id,
            sources=len(pack.sources),
            venues=len(pack.venues),
            authors=len(pack.authors),
        )
        return pack
    except Exception as e:
        logger.warning("resolve_endpoint_failed", user_id=user_id, error=str(e))
        return source_discovery.DiscoveryPack()


# ---------------------------------------------------------------------------
# GET /api/discovery/existing
# ---------------------------------------------------------------------------


class ExistingResponse(BaseModel):
    source_canonical_ids: list[str] = []
    venue_names: list[str] = []
    author_openalex_ids: list[str] = []
    author_names: list[str] = []


@router.get("/existing")
async def get_existing(current_user: dict = Depends(require_session)):
    user_id = current_user["id"]
    from sqlalchemy import text
    from database import engine as _engine

    with _engine.connect() as conn:
        source_rows = conn.execute(
            text("SELECT s.canonical_id FROM sources s JOIN user_source_subscriptions uss ON s.id = uss.source_id WHERE uss.user_id = :uid"),
            {"uid": user_id},
        ).fetchall()
        venue_rows = conn.execute(
            text("SELECT venue_name FROM tracked_venues WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchall()
        author_rows = conn.execute(
            text("SELECT openalex_id, name FROM tracked_authors WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchall()

    return ExistingResponse(
        source_canonical_ids=[r[0] for r in source_rows if r[0]],
        venue_names=[r[0] for r in venue_rows],
        author_openalex_ids=[r[0] for r in author_rows if r[0]],
        author_names=[r[1] for r in author_rows],
    )


# ---------------------------------------------------------------------------
# POST /api/discovery/apply
# ---------------------------------------------------------------------------


class ApplyResponse(BaseModel):
    applied: bool = True
    counts: dict = {}


@router.post("/apply")
async def post_apply(
    body: source_discovery.ApplyRequest,
    current_user: dict = Depends(require_session),
):
    user_id = current_user["id"]
    try:
        counts = source_discovery.apply_discovery_pack(
            user_id=user_id,
            sources=body.sources,
            venues=body.venues,
            authors=body.authors,
        )
        logger.info("apply_endpoint", user_id=user_id, counts=counts)
        return ApplyResponse(applied=True, counts=counts)
    except Exception as e:
        logger.error("apply_endpoint_failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /api/discovery/run  — async background job (Story 15.1)
# GET  /api/discovery/run/{run_id}
# ---------------------------------------------------------------------------

# Run rate limiter — reuse expand pattern (10 per hour per user)
_run_calls: dict[int, list[float]] = {}


def _check_run_rate_limit(user_id: int) -> Optional[int]:
    now = time.monotonic()
    window = EXPAND_RATE_WINDOW_SECONDS
    history = _run_calls.setdefault(user_id, [])
    history[:] = [t for t in history if t > now - window]
    if len(history) >= EXPAND_RATE_LIMIT:
        return max(int(window - (now - history[0])) + 1, 1)
    history.append(now)
    return None


class DiscoveryRunRequest(BaseModel):
    thesis_text: str
    keywords: List[str] = []


class DiscoveryRunResponse(BaseModel):
    run_id: int
    status: str


class DiscoveryRunStatusResponse(BaseModel):
    run_id: int
    status: str
    pack: Optional[source_discovery.DiscoveryPack] = None


@router.post("/run", response_model=DiscoveryRunResponse, status_code=202)
async def post_discovery_run(
    body: DiscoveryRunRequest,
    response: Response,
    current_user: dict = Depends(require_session),
):
    """Start a background discovery job and return a run_id immediately.

    If a completed run for the same thesis_text already exists, returns it
    without spawning a new task (input-hash dedup).
    """
    from sqlalchemy import text as _text
    from database import engine as _engine

    user_id = current_user["id"]
    retry_after = _check_run_rate_limit(user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Discovery run rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    sanitized = source_discovery.sanitize(body.thesis_text)
    input_hash = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()

    # Check for a recent completed run with the same input (dedup)
    with _engine.connect() as conn:
        row = conn.execute(
            _text(
                "SELECT id, status FROM discovery_runs "
                "WHERE user_id = :uid AND expand_input = :h AND status = 'done' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"uid": user_id, "h": input_hash},
        ).fetchone()
        if row:
            logger.info("run_cache_hit", user_id=user_id, run_id=row[0])
            return DiscoveryRunResponse(run_id=row[0], status="done")

        result = conn.execute(
            _text(
                "INSERT INTO discovery_runs (user_id, expand_input, status, created_at) "
                "VALUES (:uid, :h, 'pending', datetime('now'))"
            ),
            {"uid": user_id, "h": input_hash},
        )
        conn.commit()
        run_id = result.lastrowid

    asyncio.create_task(
        source_discovery.run_discovery_job(
            run_id=run_id,
            user_id=user_id,
            thesis_text=body.thesis_text,
            keywords=body.keywords or None,
        )
    )
    logger.info("run_started", user_id=user_id, run_id=run_id)
    return DiscoveryRunResponse(run_id=run_id, status="pending")


@router.get("/run/{run_id}", response_model=DiscoveryRunStatusResponse)
async def get_discovery_run(
    run_id: int,
    current_user: dict = Depends(require_session),
):
    """Poll a discovery run for status and result.

    Returns 404 if the run does not exist or belongs to a different user
    (isolation enforced via user_id from require_session).
    """
    from sqlalchemy import text as _text
    from database import engine as _engine

    user_id = current_user["id"]
    with _engine.connect() as conn:
        row = conn.execute(
            _text(
                "SELECT id, status, pack_result_json "
                "FROM discovery_runs WHERE id = :rid AND user_id = :uid"
            ),
            {"rid": run_id, "uid": user_id},
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Discovery run not found")

    pack: Optional[source_discovery.DiscoveryPack] = None
    if row[2]:
        try:
            pack = source_discovery.DiscoveryPack.model_validate_json(row[2])
        except Exception:
            pass

    return DiscoveryRunStatusResponse(run_id=row[0], status=row[1], pack=pack)
