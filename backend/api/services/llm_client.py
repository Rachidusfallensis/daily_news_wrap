"""Generic per-provider LLM completion dispatcher (Epic 15 — tenant LLM routing).

Takes a resolved `LLMConfig` (from `TenantLLMRouter.get_config()`) and makes one
chat-completion call against the right provider API. Never raises — returns
`None` on any failure, mirroring the contract every caller already expects
from the legacy per-service `_call_llm()` env-var ladders (config_bootstrap.py,
source_discovery.py, lit_review_llm.py).
"""
from __future__ import annotations

from typing import Optional

import httpx
import structlog

from services.tenant_llm_router import LLMConfig

logger = structlog.get_logger().bind(service="llm_client")

_DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://host.docker.internal:11434",
}


async def _chat_openai_compatible(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: Optional[str],
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
    extra_headers: Optional[dict] = None,
    disable_reasoning: bool = False,
) -> Optional[str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if disable_reasoning:
        # Best-effort (OpenRouter only — see complete()'s dispatch): proxies
        # arbitrary underlying models, some of which reason by default and
        # can burn the whole token budget before emitting the actual answer.
        # Documented as ignored by models that don't support it.
        body["reasoning"] = {"enabled": False}
    try:
        r = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
            timeout=60.0,
        )
        if not r.is_success:
            logger.warning("llm_client_openai_compatible_http", status=r.status_code, body=r.text[:300])
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("llm_client_openai_compatible_failed", error=str(e))
        return None


async def _chat_ollama(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> Optional[str]:
    try:
        r = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                # Disable reasoning outright for this single-shot structured-
                # JSON extraction — a "thinking" model (gemma3+, qwen3…)
                # otherwise emits its chain-of-thought into a separate
                # `message.thinking` field and can exhaust the token budget
                # before ever reaching `message.content`. Ollama ignores
                # `think` for models that don't support it.
                "think": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=120.0,
        )
        if not r.is_success:
            logger.warning("llm_client_ollama_http", status=r.status_code, body=r.text[:300])
            return None
        return r.json().get("message", {}).get("content")
    except Exception as e:
        logger.warning("llm_client_ollama_failed", error=str(e))
        return None


async def _chat_anthropic(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> Optional[str]:
    try:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=60.0,
        )
        if not r.is_success:
            logger.warning("llm_client_anthropic_http", status=r.status_code, body=r.text[:300])
            return None
        data = r.json()
        return data["content"][0]["text"]
    except Exception as e:
        logger.warning("llm_client_anthropic_failed", error=str(e))
        return None


async def _chat_gemini(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> Optional[str]:
    try:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    # Best-effort: 2.x-series Gemini models think by default.
                    # Disables it on models that support disabling
                    # (Flash/Flash-Lite); Pro enforces a minimum and clamps
                    # instead of erroring. Not live-verified — no Gemini key
                    # available to test against.
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=60.0,
        )
        if not r.is_success:
            logger.warning("llm_client_gemini_http", status=r.status_code, body=r.text[:300])
            return None
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.warning("llm_client_gemini_failed", error=str(e))
        return None


async def complete(
    config: LLMConfig,
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Make one chat-completion call using a resolved tenant `LLMConfig`.

    Never raises — returns `None` on any failure (unreachable provider, bad
    response shape, unknown provider, missing key).
    """
    provider = config.provider
    base_url = config.base_url or _DEFAULT_BASE_URLS.get(provider, "")

    async with httpx.AsyncClient() as client:
        if provider == "openrouter":
            return await _chat_openai_compatible(
                client, base_url, config.api_key, config.model, system_prompt, user_message,
                temperature, max_tokens,
                extra_headers={"HTTP-Referer": "https://github.com/basira", "X-Title": "Basira"},
                disable_reasoning=True,
            )
        if provider == "openai":
            return await _chat_openai_compatible(
                client, base_url, config.api_key, config.model, system_prompt, user_message,
                temperature, max_tokens,
            )
        if provider == "ollama":
            return await _chat_ollama(
                client, base_url, config.model, system_prompt, user_message, temperature, max_tokens,
            )
        if provider == "anthropic":
            if not config.api_key:
                logger.warning("llm_client_anthropic_missing_key")
                return None
            return await _chat_anthropic(
                client, config.api_key, config.model, system_prompt, user_message, temperature, max_tokens,
            )
        if provider == "gemini":
            if not config.api_key:
                logger.warning("llm_client_gemini_missing_key")
                return None
            return await _chat_gemini(
                client, config.api_key, config.model, system_prompt, user_message, temperature, max_tokens,
            )

        logger.warning("llm_client_unknown_provider", provider=provider)
        return None
