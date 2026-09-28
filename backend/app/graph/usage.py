"""Token usage + cost accounting for LLM calls (Phase 6).

Parses the ``response.usage`` block from OpenAI-compatible responses (MiniMax /
OpenRouter both return it) and accumulates per-day token counts + estimated cost
in Redis. Surfaced on ``/admin/performance`` so operators can answer "how much did
today cost?" without a heavyweight trace backend.

This is the prerequisite for either a Langfuse rollout (which consumes the same
``usage`` block) or a standalone cost dashboard. It is intentionally dependency-
free: stdlib + Redis counters, matching the existing ``_record_llm_latency`` pattern.

Cost model: env-configurable per-million-token rates by provider. Defaults are the
documented MiniMax rates (the primary provider). When rates are unset, only token
counts are tracked (cost = 0) so the path never blocks on missing pricing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Redis keys (per-day so the dashboard can chart a trend without aggregation queries).
# Format: llm:tokens:{type}:{YYYY-MM-DD}  (type ∈ input, output, cached)
#         llm:cost:{YYYY-MM-DD}            (micro-USD: USD × 1,000,000 to stay integer)
_RKEY_TOKEN_INPUT = "llm:tokens:input:{day}"
_RKEY_TOKEN_OUTPUT = "llm:tokens:output:{day}"
_RKEY_TOKEN_CACHED = "llm:tokens:cached:{day}"
_RKEY_COST = "llm:cost:{day}"
_TOKEN_TTL_SECONDS = 90 * 86400  # 90 days — enough for a monthly cost trend


@dataclass(frozen=True)
class TokenUsage:
    """Parsed usage block from an OpenAI-compatible LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0  # prompt_cache_hit_tokens (MiniMax) / cached_tokens (OpenAI)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _field(obj: object, key: str) -> object | None:
    """Read ``key`` from a dict- or attribute-style usage object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _cached_tokens(usage_obj: object) -> int:
    """Cached-prompt tokens across the key shapes the providers/LangChain emit.

    Covers, in order:
    - MiniMax's OpenAI-compatible ``prompt_cache_hit_tokens``;
    - OpenAI/OpenRouter ``cached_tokens`` or
      ``prompt_tokens_details.cached_tokens``;
    - LangChain's *normalized* ``usage_metadata`` shape
      ``input_token_details.cache_read``. langchain-openai converts the provider
      block into this shape before the agent loop sees it, so without this key
      a genuine cache hit was recorded as 0 — the metrics said "no caching"
      regardless of what the provider actually did (PERF-05 follow-up).
    """
    direct = _field(usage_obj, "prompt_cache_hit_tokens") or _field(usage_obj, "cached_tokens")
    if direct:
        return int(direct)
    details = _field(usage_obj, "prompt_tokens_details")
    if details is not None and (value := _field(details, "cached_tokens")):
        return int(value)
    normalized = _field(usage_obj, "input_token_details")
    if normalized is not None and (value := _field(normalized, "cache_read")):
        return int(value)
    return 0


def parse_usage(usage_obj: object | None) -> TokenUsage:
    """Extract token counts from an OpenAI-compatible ``response.usage`` object.

    Handles both attribute-style (langchain ``response_usage``) and dict-style
    (raw OpenAI response) objects, plus provider-specific cached-token keys.
    Returns ``TokenUsage(0,0,0)`` on anything unrecognized — never raises.
    """
    if usage_obj is None:
        return TokenUsage()
    try:
        prompt = int(_field(usage_obj, "prompt_tokens") or _field(usage_obj, "input_tokens") or 0)
        completion = int(
            _field(usage_obj, "completion_tokens") or _field(usage_obj, "output_tokens") or 0
        )
        return TokenUsage(prompt, completion, _cached_tokens(usage_obj))
    except (TypeError, ValueError):
        return TokenUsage()


def _estimate_cost(usage: TokenUsage) -> float:
    """Estimate USD cost from token counts + configured per-million rates.

    Cached tokens are free (provider-side cache hit). Returns 0.0 when rates are
    unset or the settings object doesn't expose them — never raises.
    """
    try:
        from app.core.config import get_settings

        s = get_settings()
        in_rate = float(getattr(s, "llm_cost_per_mtok_input", 0) or 0)
        out_rate = float(getattr(s, "llm_cost_per_mtok_output", 0) or 0)
        billable_input = max(usage.prompt_tokens - usage.cached_tokens, 0)
        return (billable_input / 1_000_000) * in_rate + (
            usage.completion_tokens / 1_000_000
        ) * out_rate
    except Exception:  # noqa: BLE001
        return 0.0


async def record_token_usage(usage_obj: object | None) -> TokenUsage:
    """Parse usage, accumulate tokens + cost in Redis (best-effort, non-fatal).

    Called after every LLM response from inside the agent loop, so it uses the
    async Redis client: the sync client here would block the event loop on every
    turn (REL-02). Returns the parsed ``TokenUsage`` so the caller (the agent
    loop) can log it inline if desired.
    """
    usage = parse_usage(usage_obj)
    if usage.total_tokens == 0:
        return usage
    try:
        from app.core.redis import get_redis

        day = _today_utc()
        r = await get_redis()
        pipe = r.pipeline()
        pipe.incrby(_RKEY_TOKEN_INPUT.format(day=day), usage.prompt_tokens)
        pipe.incrby(_RKEY_TOKEN_OUTPUT.format(day=day), usage.completion_tokens)
        if usage.cached_tokens:
            pipe.incrby(_RKEY_TOKEN_CACHED.format(day=day), usage.cached_tokens)
        cost = _estimate_cost(usage)
        if cost > 0:
            # Store cost as micro-USD (USD × 1,000,000) to stay integer-accurate.
            pipe.incrby(_RKEY_COST.format(day=day), int(cost * 1_000_000))
        for key in (
            _RKEY_TOKEN_INPUT.format(day=day),
            _RKEY_TOKEN_OUTPUT.format(day=day),
            _RKEY_TOKEN_CACHED.format(day=day),
            _RKEY_COST.format(day=day),
        ):
            pipe.expire(key, _TOKEN_TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        logger.debug("failed to record token usage to redis", exc_info=True)
    return usage


def collect_token_usage(day: str | None = None) -> dict:
    """Read today's (or ``day``'s) accumulated token counts + cost from Redis.

    Returns a dict with input/output/cached/total tokens, estimated USD cost,
    and the day string. Best-effort: missing keys read as 0.

    Sync by design: its only caller (``core.ops_health.collect_queue_health``) is
    a sync snapshot that the API runs via ``asyncio.to_thread``.
    """
    day = day or _today_utc()
    try:
        from app.core.redis import get_redis_sync, sync_value

        r = get_redis_sync()
        inp = int(sync_value(r.get(_RKEY_TOKEN_INPUT.format(day=day))) or 0)
        out = int(sync_value(r.get(_RKEY_TOKEN_OUTPUT.format(day=day))) or 0)
        cached = int(sync_value(r.get(_RKEY_TOKEN_CACHED.format(day=day))) or 0)
        cost_micro = int(sync_value(r.get(_RKEY_COST.format(day=day))) or 0)
        return {
            "day": day,
            "tokens_input": inp,
            "tokens_output": out,
            "tokens_cached": cached,
            "tokens_total": inp + out,
            "estimated_cost_usd": round(cost_micro / 1_000_000, 4),
        }
    except Exception:  # noqa: BLE001
        return {
            "day": day,
            "tokens_input": 0,
            "tokens_output": 0,
            "tokens_cached": 0,
            "tokens_total": 0,
            "estimated_cost_usd": 0.0,
        }
