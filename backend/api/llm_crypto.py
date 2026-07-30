"""
LLM Crypto — Fernet encryption for stored API keys (FR-MT-71, NFR-T10).

Rules:
  - encrypt_key(raw) → bytes : never logs raw
  - decrypt_key(enc) → str : raises LLMCryptoError on invalid token
  - LLMCryptoError : subclass of Exception, caught at router level → HTTP 503
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class LLMCryptoError(Exception):
    pass


def _get_fernet() -> Fernet:
    key = os.getenv("FERNET_SECRET_KEY", "").strip()
    if not key:
        raise LLMCryptoError("FERNET_SECRET_KEY not set — cannot store API keys securely")
    try:
        return Fernet(key.encode())
    except Exception:
        raise LLMCryptoError("FERNET_SECRET_KEY is malformed")


def encrypt_key(raw: str) -> bytes:
    if not raw:
        raise LLMCryptoError("Cannot encrypt empty key")
    return _get_fernet().encrypt(raw.encode())


def decrypt_key(enc: bytes) -> str:
    try:
        return _get_fernet().decrypt(enc).decode()
    except InvalidToken:
        raise LLMCryptoError("Cannot decrypt API key — FERNET_SECRET_KEY may have rotated")


def generate_fernet_key() -> str:
    """Utility to generate a new Fernet key (run once at deployment)."""
    return Fernet.generate_key().decode()
