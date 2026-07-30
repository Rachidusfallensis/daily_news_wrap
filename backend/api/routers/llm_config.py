"""
LLM Config router — CRUD + verify + detect endpoints (Epic 15, FR-MT-72..74).

ONE ROUTER PER FILE rule: all /api/llm-config/* routes live here.
user_id comes ONLY from require_session (FR-MT-76, NFR-T1).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Any, Optional

from auth import require_session
from database import get_db, get_llm_config, set_llm_config, UserLLMConfig
from llm_crypto import LLMCryptoError, encrypt_key
from llm_providers import DESCRIPTORS, detect_provider, verify_connection
from services.tenant_llm_router import TenantLLMRouter

router = APIRouter(prefix="/api/llm-config", tags=["llm-config"])
logger = structlog.get_logger().bind(service="llm_config")

VALID_ROLES = {"scorer", "embedder", "review", "ask", "onboarding"}


# ── Schemas ──────────────────────────────────────────────────────────────────

class LLMConfigOut(BaseModel):
    role: str
    provider: str
    model: str
    api_key_configured: bool
    base_url: Optional[str] = None
    source: str = "user"

class LLMConfigIn(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None   # None for Ollama
    base_url: Optional[str] = None

class VerifyRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class DetectRequest(BaseModel):
    api_key: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(_: dict = Depends(require_session)) -> list[dict[str, Any]]:
    """Return provider descriptors for UI form rendering (FR-MT-74)."""
    return [d.to_dict() for d in DESCRIPTORS]


@router.get("")
async def get_user_llm_configs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_session),
) -> list[LLMConfigOut]:
    """Return all configured LLM roles for the current user (no keys)."""
    user_id = current_user["id"]
    rows = db.query(UserLLMConfig).filter(UserLLMConfig.user_id == user_id).all()
    return [
        LLMConfigOut(
            role=row.role,
            provider=row.provider,
            model=row.model,
            api_key_configured=row.api_key_enc is not None,
            base_url=row.base_url,
        )
        for row in rows
    ]


@router.put("/{role}")
async def upsert_llm_config(
    role: str,
    body: LLMConfigIn,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_session),
):
    """Create or update LLM config for a role (key encrypted at rest)."""
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'. Must be one of {VALID_ROLES}")

    user_id = current_user["id"]
    api_key_enc: bytes | None = None

    if body.api_key:
        try:
            api_key_enc = encrypt_key(body.api_key)
        except LLMCryptoError as e:
            raise HTTPException(status_code=503, detail=str(e))
    else:
        # No key submitted — preserve the existing encrypted key rather than
        # wiping it (Settings edit form never pre-fills api_key; submitting
        # without one must not destroy a previously stored key).
        existing = get_llm_config(db, user_id, role)
        api_key_enc = existing.api_key_enc if existing else None

    try:
        set_llm_config(db, user_id, role, body.provider, body.model, api_key_enc, body.base_url)
    except Exception as e:
        logger.error("llm_config_save_failed", user_id=user_id, role=role, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save LLM configuration")

    # Invalidate cache so next LLM call uses fresh config
    TenantLLMRouter.invalidate(user_id)

    logger.info("llm_config_saved", user_id=user_id, role=role, provider=body.provider)
    return {"status": "ok", "role": role}


@router.delete("/{role}")
async def delete_llm_config(
    role: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_session),
):
    """Delete LLM config for a role (falls back to global env vars)."""
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'")

    user_id = current_user["id"]
    row = get_llm_config(db, user_id, role)
    if row:
        db.delete(row)
        db.commit()
        TenantLLMRouter.invalidate(user_id)

    return {"status": "ok", "role": role}


@router.post("/verify")
async def verify_llm_config(
    body: VerifyRequest,
    _: dict = Depends(require_session),
) -> dict:
    """Test provider connectivity with provided credentials (FR-MT-73)."""
    result = await verify_connection(
        provider=body.provider,
        api_key=body.api_key or "",
        base_url=body.base_url or "",
    )
    return result


@router.post("/detect")
async def detect_llm_provider(
    body: DetectRequest,
    _: dict = Depends(require_session),
) -> dict:
    """Best-effort detect provider from API key shape (FR-MT-74)."""
    provider = detect_provider(body.api_key)
    return {"provider": provider}
