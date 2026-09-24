"""Redis-backed LLM observability counters (process-agnostic).

The live telemetry tiles read these keys directly (see ``app.core.ops_health``),
so the key names and TTLs are a dashboard contract, not an implementation
detail. The async client is mandatory: these are written from inside the agent
loop, where a sync Redis round trip would block the event loop that also serves
webhook acks and inline web-chat turns (REL-02).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RKEY_429 = "llm:minimax_429s"  # INCR on 429, EXPIRE 60 (rolling minute)
_RKEY_INVOKE_COUNT = "llm:invoke_count"
_RKEY_INVOKE_MS = "llm:invoke_total_ms"


async def _record_llm_latency(ms: int) -> None:
    """Persist LLM call latency + count to Redis (best-effort, non-fatal).

    Called from inside the agent loop, so it uses the async client: a sync Redis
    round trip here would block the event loop that also serves webhook acks and
    inline web-chat turns (REL-02).
    """
    try:
        from app.core.redis import get_redis

        r = await get_redis()
        pipe = r.pipeline()
        pipe.incr(_RKEY_INVOKE_COUNT)
        pipe.incrby(_RKEY_INVOKE_MS, ms)
        pipe.expire(_RKEY_INVOKE_COUNT, 120)
        pipe.expire(_RKEY_INVOKE_MS, 120)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm latency to redis", exc_info=True)


async def _record_llm_429() -> None:
    """Increment MiniMax 429 counter in Redis (best-effort, non-fatal).

    Async client for the same reason as :func:`_record_llm_latency`.
    """
    try:
        from app.core.redis import get_redis

        r = await get_redis()
        await r.incr(_RKEY_429)
        await r.expire(_RKEY_429, 60)  # rolling 1-minute window
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm 429 to redis", exc_info=True)
