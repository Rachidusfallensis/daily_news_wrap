"""Tests for llm_crypto — Fernet encryption for stored API keys (Story 15.1, FR-MT-71).

Run inside Docker:
    docker compose exec api pytest test_llm_crypto.py -v
"""
import pytest

from llm_crypto import LLMCryptoError, decrypt_key, encrypt_key, generate_fernet_key


def test_roundtrip(monkeypatch):
    key = generate_fernet_key()
    monkeypatch.setenv("FERNET_SECRET_KEY", key)
    enc = encrypt_key("sk-or-test-key")
    assert decrypt_key(enc) == "sk-or-test-key"


def test_no_fernet_key(monkeypatch):
    monkeypatch.delenv("FERNET_SECRET_KEY", raising=False)
    with pytest.raises(LLMCryptoError, match="not set"):
        encrypt_key("anything")


def test_invalid_token(monkeypatch):
    monkeypatch.setenv("FERNET_SECRET_KEY", generate_fernet_key())
    with pytest.raises(LLMCryptoError, match="decrypt"):
        decrypt_key(b"notvalidciphertext")


def test_empty_key(monkeypatch):
    monkeypatch.setenv("FERNET_SECRET_KEY", generate_fernet_key())
    with pytest.raises(LLMCryptoError):
        encrypt_key("")
