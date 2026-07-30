import hashlib
import json
import os
import re
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from prompt import SYSTEM_PROMPT
from prompt_builder import PromptBuilder, UserScoringContext
from scorer_logic import (
    _VALID_CONTRIBUTION_TYPES,
    _VALID_RE_DOC_TYPES,
    clamp_float as _clamp_float,
    compute_content_cap,
    extract_facets,
)

app = FastAPI(title="Baṣīra Scorer")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SCORER_MODEL = os.getenv("SCORER_MODEL", "google/gemini-flash-1.5")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host-gateway:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
UNI_OLLAMA_URL = os.getenv("UNI_OLLAMA_URL", "")
UNI_OLLAMA_MODEL = os.getenv("UNI_OLLAMA_MODEL", "")
UNI_OLLAMA_API_KEY = os.getenv("UNI_OLLAMA_API_KEY", "")
SCORER_MAX_CHARS = int(os.getenv("SCORER_MAX_CHARS", "6000"))
API_BASE = "http://api:8000"
API_SECRET = os.getenv("API_SECRET", "changeme")
# Story MT-LLM-gate — route scoring through each tenant's own configured LLM
# before falling back to the shared uni/openrouter/ollama ladder below.
# Defaults OFF: this is the highest-blast-radius change in the LLM-router
# refactor (hot path for every article, every existing tenant) — flip on
# only after Phase 6 integration verification passes.
SCORER_TENANT_ROUTING_ENABLED = os.getenv("SCORER_TENANT_ROUTING_ENABLED", "false").lower() == "true"

INTERNAL_HEADERS = {"X-Internal-Secret": API_SECRET, "Content-Type": "application/json"}


class ScoreRequest(BaseModel):
    article_id: int
    title: str
    content_text: str
    rss_summary: str = ""
    paper_meta_json: Optional[str] = None
    user_id: int  # Story 2.7, FR-MT-9 — mandatory
    user_context: Optional[Dict] = None  # Story 5.2, FR-MT-27


class ScoreResult(BaseModel):
    score: float
    tags: List[str] = []
    summary_bullets: List[str] = []
    reason: str = ""
    contribution_type: Optional[str] = None
    re_document_type: Optional[str] = None
    novelty: Optional[float] = None
    rigor: Optional[float] = None
    relevance_to_topics: Optional[float] = None
    facets_json: Optional[str] = None  # Story 10.4 — serialized per-dimension facets


def _resolve_system_prompt(req: ScoreRequest) -> str:
    """Return the appropriate system prompt for this request.

    When user_context is provided, build a dynamic prompt via PromptBuilder.
    Otherwise, return the static SYSTEM_PROMPT (backward compat, NFR-T4).
    """
    if not req.user_context:
        return SYSTEM_PROMPT
    ctx = UserScoringContext(**req.user_context)
    return PromptBuilder.build(ctx)


async def _resolve_cached_prompt(
    client: httpx.AsyncClient, user_context: Dict, user_id: int
) -> str:
    """Resolve system prompt with API-backed cache (FR-MT-29).

    1. Hash user_context → compare with stored prompt_cache_hash.
    2. Hit → return cached prompt_cache_text.
    3. Miss → build via PromptBuilder, store via PUT.
    4. API failure → build anyway (graceful degradation, NFR-T6).
    """
    raw = json.dumps(user_context, sort_keys=True)
    current_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

    try:
        resp = await client.get(
            f"{API_BASE}/api/internal/users/{user_id}/prompt-cache",
            headers=INTERNAL_HEADERS,
            timeout=5,
        )
        if resp.is_success:
            data = resp.json()
            if data.get("hash") == current_hash and data.get("text"):
                return data["text"]
    except Exception:
        pass

    ctx = UserScoringContext(**user_context)
    prompt = PromptBuilder.build(ctx)

    try:
        await client.put(
            f"{API_BASE}/api/internal/users/{user_id}/prompt-cache",
            json={"hash": current_hash, "text": prompt},
            headers=INTERNAL_HEADERS,
            timeout=5,
        )
    except Exception:
        pass

    return prompt


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """Return the substring of `text` that forms a balanced JSON object starting at `start`."""
    depth = 0
    in_string = False
    escape = False
    for i, c in enumerate(text[start:]):
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : start + i + 1]
    return None


def extract_json_from_text(text: str) -> Optional[dict]:
    """Extract a JSON object from model output.

    Handles: plain JSON, markdown code blocks, preamble/thinking text,
    and responses truncated mid-string at a token limit (scans backward
    from the last '{' so a complete outer object is preferred over a
    fragment inside a truncated response).
    """
    text = text.strip()

    # 1. Direct parse — fastest path for well-behaved models
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code blocks
    for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
        for m in re.findall(pattern, text, re.DOTALL):
            try:
                result = json.loads(m)
                if isinstance(result, dict) and result:
                    return result
            except json.JSONDecodeError:
                pass

    # 3. Balanced-brace scan — scans BACKWARD so the last complete JSON object
    #    wins.  This handles models that emit <thinking>...</thinking> preamble
    #    (which may contain '{...}' fragments) before the actual JSON response,
    #    and also handles token-limit truncation where earlier inner objects may
    #    be complete while the outer object is not.
    brace_positions = [i for i, c in enumerate(text) if c == "{"]
    for start in reversed(brace_positions):
        candidate = _extract_balanced_json(text, start)
        if candidate:
            try:
                result = json.loads(candidate)
                if isinstance(result, dict) and result:
                    return result
            except json.JSONDecodeError:
                continue

    return None


def validate_score_result(data: dict, facet_schema: Optional[dict] = None) -> ScoreResult:
    score = data.get("score", 5)
    try:
        score = float(score)
        score = max(0.0, min(10.0, score))
    except (TypeError, ValueError):
        score = 5.0

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags[:5]]

    summary_bullets = data.get("summary_bullets", [])
    if not isinstance(summary_bullets, list):
        summary_bullets = []
    summary_bullets = [str(b) for b in summary_bullets[:4]]

    reason = data.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    contribution_type = data.get("contribution_type")
    if contribution_type not in _VALID_CONTRIBUTION_TYPES:
        contribution_type = None

    re_document_type = data.get("re_document_type")
    if re_document_type not in _VALID_RE_DOC_TYPES:
        re_document_type = None

    facets_json = extract_facets(data, facet_schema)  # Story 10.4

    return ScoreResult(
        score=score,
        tags=tags,
        summary_bullets=summary_bullets,
        reason=reason,
        contribution_type=contribution_type,
        re_document_type=re_document_type,
        novelty=_clamp_float(data.get("novelty")),
        rigor=_clamp_float(data.get("rigor")),
        relevance_to_topics=_clamp_float(data.get("relevance_to_topics")),
        facets_json=facets_json,
    )


async def score_with_uni_server(
    client: httpx.AsyncClient,
    user_message: str,
    system_prompt: str = SYSTEM_PROMPT,
    facet_schema: Optional[dict] = None,
) -> Optional[ScoreResult]:
    """Tier 1: University GPU server (OpenAI-compatible API)."""
    if not UNI_OLLAMA_URL or not UNI_OLLAMA_MODEL or not UNI_OLLAMA_API_KEY:
        return None

    try:
        resp = await client.post(
            f"{UNI_OLLAMA_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {UNI_OLLAMA_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": UNI_OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            timeout=90,
        )
        if not resp.is_success:
            print(f"Uni server error {resp.status_code}: {resp.text[:300]}")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_from_text(content)
        if parsed:
            return validate_score_result(parsed, facet_schema)
        print(f"Uni server: could not parse JSON from response: {content[:200]}")
    except Exception as e:
        print(f"Uni server scoring failed: {e}")

    return None


async def score_with_openrouter(
    client: httpx.AsyncClient,
    user_message: str,
    system_prompt: str = SYSTEM_PROMPT,
    facet_schema: Optional[dict] = None,
) -> Optional[ScoreResult]:
    if not OPENROUTER_API_KEY or not OPENROUTER_API_KEY.startswith("sk-"):
        return None

    try:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/basira",
                "X-Title": "Basira",
            },
            json={
                "model": SCORER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
                # Best-effort: OpenRouter proxies arbitrary underlying models,
                # some of which reason by default (same failure mode as
                # Ollama's "thinking" models below — reasoning tokens can eat
                # the whole budget before the JSON answer is ever emitted).
                # OpenRouter's unified reasoning control is documented as
                # ignored by models that don't support it, so safe to always
                # send. Not live-verified against every possible routed model.
                "reasoning": {"enabled": False},
            },
            timeout=60,
        )
        if not resp.is_success:
            # Log full body so the user can see the actual OpenRouter error
            print(f"OpenRouter error {resp.status_code}: {resp.text[:500]}")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_from_text(content)
        if parsed:
            return validate_score_result(parsed, facet_schema)
        print(f"OpenRouter: could not parse JSON from response: {content[:200]}")
    except Exception as e:
        print(f"OpenRouter scoring failed: {e}")

    return None


async def score_with_ollama(
    client: httpx.AsyncClient,
    user_message: str,
    system_prompt: str = SYSTEM_PROMPT,
    facet_schema: Optional[dict] = None,
) -> Optional[ScoreResult]:
    if not OLLAMA_URL:
        return None

    try:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                # Reasoning/"thinking" models (gemma3+, qwen3, deepseek-r1…)
                # emit their chain-of-thought into a separate `message.thinking`
                # field and can burn an arbitrarily large token budget doing
                # so before ever reaching `message.content` — which then comes
                # back empty. We don't want reasoning for a single-shot
                # structured-JSON task regardless of which model is
                # configured, so disable it outright rather than trying to
                # guess a budget big enough for an unknown model. Ollama
                # ignores `think` for models that don't support it.
                "think": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1024,
                },
            },
            timeout=120,
        )
        if not resp.is_success:
            print(f"Ollama error {resp.status_code}: {resp.text[:300]}")
            return None
        data = resp.json()
        content = data["message"]["content"]
        parsed = extract_json_from_text(content)
        if parsed:
            return validate_score_result(parsed, facet_schema)
        print(f"Ollama: could not parse JSON from response: {content[:200]}")
    except Exception as e:
        print(f"Ollama scoring failed: {e}")

    return None


async def _get_tenant_llm_config(
    client: httpx.AsyncClient, user_id: int, role: str = "scorer"
) -> Optional[dict]:
    """Fetch the tenant's resolved LLM config from the api container.

    scorer.py has no DB access (separate deploy, no DB driver) — this crosses
    the same internal-network trust boundary as prompt-cache/feedback-examples.
    Returns None on any failure (mirrors _resolve_cached_prompt's try/except).
    """
    try:
        resp = await client.get(
            f"{API_BASE}/api/internal/users/{user_id}/llm-config",
            params={"role": role},
            headers=INTERNAL_HEADERS,
            timeout=5,
        )
        if resp.is_success:
            return resp.json()
    except Exception:
        pass
    return None


async def _score_with_tenant_config(
    client: httpx.AsyncClient,
    tenant_cfg: dict,
    user_message: str,
    system_prompt: str,
    facet_schema: Optional[dict],
) -> Optional[ScoreResult]:
    """Dispatch one scoring call using a tenant-resolved LLM config.

    Small duplicate of backend/api/services/llm_client.py's provider
    branching — scorer.py is a separate container/deploy with no shared-code
    mechanism to the api image, so this ~40-line duplication is the accepted
    tradeoff over introducing a cross-container package dependency.
    """
    provider = tenant_cfg.get("provider")
    model = tenant_cfg.get("model")
    api_key = tenant_cfg.get("api_key")
    base_url = tenant_cfg.get("base_url")

    try:
        if provider in ("openrouter", "openai"):
            url = (base_url or (
                "https://openrouter.ai/api/v1" if provider == "openrouter"
                else "https://api.openai.com/v1"
            )).rstrip("/") + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            }
            if provider == "openrouter":
                # Best-effort: see matching comment on score_with_openrouter()
                # above — OpenRouter proxies arbitrary models, some reasoning
                # by default. Not applicable to plain OpenAI's API shape.
                body["reasoning"] = {"enabled": False}
            resp = await client.post(url, headers=headers, json=body, timeout=60)
            if not resp.is_success:
                print(f"Tenant {provider} error {resp.status_code}: {resp.text[:300]}")
                return None
            content = resp.json()["choices"][0]["message"]["content"]

        elif provider == "ollama":
            url = (base_url or "http://host.docker.internal:11434").rstrip("/") + "/api/chat"
            resp = await client.post(url, json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                # See matching comment on score_with_ollama() above — disable
                # reasoning outright rather than guessing a budget.
                "think": False,
                "options": {"temperature": 0.3, "num_predict": 1024},
            }, timeout=120)
            if not resp.is_success:
                print(f"Tenant ollama error {resp.status_code}: {resp.text[:300]}")
                return None
            content = resp.json().get("message", {}).get("content")

        elif provider == "anthropic":
            if not api_key:
                return None
            resp = await client.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }, json={
                "model": model,
                "max_tokens": 2048,
                "temperature": 0.3,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            }, timeout=60)
            if not resp.is_success:
                print(f"Tenant anthropic error {resp.status_code}: {resp.text[:300]}")
                return None
            content = resp.json()["content"][0]["text"]

        elif provider == "gemini":
            if not api_key:
                return None
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            resp = await client.post(url, json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 2048,
                    # Best-effort: 2.x-series Gemini models think by default.
                    # thinkingBudget: 0 disables it on models that support
                    # disabling (Flash/Flash-Lite); Pro enforces a minimum
                    # budget and will just clamp instead of erroring. Not
                    # live-verified — no Gemini key available to test against.
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }, timeout=60)
            if not resp.is_success:
                print(f"Tenant gemini error {resp.status_code}: {resp.text[:300]}")
                return None
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

        else:
            print(f"Tenant scoring: unknown provider '{provider}'")
            return None

        parsed = extract_json_from_text(content) if content else None
        if parsed:
            return validate_score_result(parsed, facet_schema)
        print(f"Tenant {provider}: could not parse JSON from response")
    except Exception as e:
        print(f"Tenant {provider} scoring failed: {e}")

    return None


async def build_preference_block(client: httpx.AsyncClient, user_id: int = 1) -> str:
    """Build a compact, structured preference profile from the full feedback history.

    Strategy (backed by LLM-Rec / NAACL 2024 findings):
    - Tag frequency aggregation over the entire history outperforms raw title lists
      by +15-22 % on ranking accuracy while using 3-4x fewer tokens.
    - Contrastive structure (liked vs. disliked) is essential; positive-only prompts
      over-generalise and dilute the signal.
    - Hard budget: the returned block stays under ~220 tokens regardless of history size.
    - Cold-start guard: block is omitted until at least 3 interactions exist.
    - User-scoped (FR-MT-31): passes user_id so the API filters by the user's own data.
    """
    try:
        resp = await client.get(
            f"{API_BASE}/api/internal/feedback-examples",
            params={"user_id": user_id},
            headers=INTERNAL_HEADERS,
            timeout=5,
        )
        if not resp.is_success:
            return ""

        data = resp.json()
        total = data.get("total_liked", 0) + data.get("total_disliked", 0)
        if total < 3:
            # Not enough signal yet — avoid noisy cold-start bias
            return ""

        liked_tags: list[dict] = data.get("liked_tags", [])
        disliked_tags: list[dict] = data.get("disliked_tags", [])
        liked_examples: list[dict] = data.get("liked_examples", [])
        disliked_examples: list[dict] = data.get("disliked_examples", [])

        lines: list[str] = ["\n\n---\n## Reader Preference Profile\n"]

        # --- Tag frequency block (most signal-dense part) ---
        if liked_tags:
            tag_str = ", ".join(e["tag"] for e in liked_tags[:8])
            lines.append(f"**Consistently enjoys (ranked by frequency):** {tag_str}")

        if disliked_tags:
            tag_str = ", ".join(e["tag"] for e in disliked_tags[:5])
            lines.append(f"**Consistently avoids:** {tag_str}")

        # --- Contrastive examples (2-3 liked, 1-2 disliked) ---
        if liked_examples:
            lines.append("\n**Representative liked articles:**")
            for ex in liked_examples[:4]:
                tag_str = f" [{', '.join(ex['tags'][:4])}]" if ex.get("tags") else ""
                title = ex["title"][:80].rstrip()
                lines.append(f'- "{title}"{tag_str}')

        if disliked_examples:
            lines.append("\n**Representative disliked articles:**")
            for ex in disliked_examples[:2]:
                tag_str = f" [{', '.join(ex['tags'][:3])}]" if ex.get("tags") else ""
                title = ex["title"][:80].rstrip()
                lines.append(f'- "{title}"{tag_str}')

        lines.append(
            "\nCalibrate the score using these signals: "
            "depth on enjoyed topics warrants higher scores; "
            "avoided topics warrant lower scores unless the article brings exceptional new value."
        )

        return "\n".join(lines)

    except Exception:
        return ""


@app.post("/score")
async def score_article(req: ScoreRequest):
    result: Optional[ScoreResult] = None

    async with httpx.AsyncClient() as client:
        # Determine content cap — paper-aware if paper_meta_json provided
        cap = compute_content_cap(SCORER_MAX_CHARS, req.paper_meta_json)

        # Resolve system prompt — static or dynamic with API-backed cache (FR-MT-29)
        if req.user_context:
            system_prompt = await _resolve_cached_prompt(client, req.user_context, req.user_id)
        else:
            system_prompt = SYSTEM_PROMPT

        # Build user message with optional preference profile for personalisation
        content_preview = (req.content_text or req.rss_summary or "")[:cap]
        preference_block = await build_preference_block(client, user_id=req.user_id)
        user_message = f"Title: {req.title}\n\nContent:\n{content_preview}{preference_block}"

        # Story 10.4 — surface the user's facet schema to each scoring tier so
        # the LLM response is parsed into facets_json keyed by dimension IDs.
        facet_schema = (req.user_context or {}).get("facet_schema")

        # Tier 0: tenant's own configured LLM (Story MT-LLM-gate) — flagged off
        # by default; only takes effect once the tenant has a real
        # user_llm_configs row (source == "user"), never the shared fallback.
        if SCORER_TENANT_ROUTING_ENABLED:
            tenant_cfg = await _get_tenant_llm_config(client, req.user_id, role="scorer")
            if tenant_cfg and tenant_cfg.get("source") == "user":
                result = await _score_with_tenant_config(
                    client, tenant_cfg, user_message, system_prompt, facet_schema,
                )

        # Tier 1: University GPU server (highest quality, free)
        if result is None and UNI_OLLAMA_URL and UNI_OLLAMA_MODEL and UNI_OLLAMA_API_KEY:
            result = await score_with_uni_server(
                client, user_message, system_prompt, facet_schema=facet_schema,
            )

        # Tier 2: OpenRouter (cloud fallback)
        if result is None and OPENROUTER_API_KEY and OPENROUTER_API_KEY.startswith("sk-"):
            result = await score_with_openrouter(
                client, user_message, system_prompt, facet_schema=facet_schema,
            )

        # Tier 3: Local Ollama
        if result is None:
            result = await score_with_ollama(
                client, user_message, system_prompt, facet_schema=facet_schema,
            )

        # Default fallback
        if result is None:
            result = ScoreResult(
                score=5.0,
                tags=[],
                summary_bullets=[],
                reason="Scoring failed: unable to reach any LLM service.",
            )

        # Post result back to API
        try:
            resp = await client.post(
                f"{API_BASE}/api/internal/articles/{req.article_id}/score",
                json={
                    "score": result.score,
                    "tags": result.tags,
                    "summary_bullets": result.summary_bullets,
                    "reason": result.reason,
                    "contribution_type": result.contribution_type,
                    "re_document_type": result.re_document_type,
                    "novelty": result.novelty,
                    "rigor": result.rigor,
                    "relevance_to_topics": result.relevance_to_topics,
                    "user_id": req.user_id,
                    "facets_json": result.facets_json,  # Story 10.4
                },
                headers=INTERNAL_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"Failed to post score to API: {e}")
            raise

    return {"status": "ok", "score": result.score}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
