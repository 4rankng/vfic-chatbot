"""Shared ops-health snapshot (RQ queue depth + worker saturation + LLM Redis counters).

Extracted verbatim from the ``/health/queue`` handler so ``/admin/performance`` can
reuse the same live tiles without duplicating the Redis/RQ reads. The dict shape
returned here is the contract for both endpoints — do not change the keys without
updating ``/health/queue`` consumers.
"""
from __future__ import annotations


def collect_queue_health() -> dict:
    """Sync snapshot of chat-path health. Run off the event loop (``to_thread``).

    Reads are best-effort per-key (``or 0`` covers missing counters when no turns
    have run yet). A Redis/RQ connection failure will propagate to the caller, as
    it did when this logic lived inline in ``/health/queue``.
    """
    from rq import Queue, Worker

    from app.core.redis import get_redis_sync
    from app.graph.clients import (
        _RKEY_429,
        _RKEY_INVOKE_COUNT,
        _RKEY_INVOKE_MS,
    )
    from app.graph.usage import collect_token_usage

    conn = get_redis_sync()
    qd = Queue("webhook_high", connection=conn).count
    total_w = Worker.count(connection=conn)
    busy_w = sum(1 for w in (Worker.all(connection=conn) or []) if w.get_current_job() is not None)

    # LLM metrics from Redis counters (best-effort, may be missing if no turns yet).
    invoke_count = int(conn.get(_RKEY_INVOKE_COUNT) or 0)
    invoke_total_ms = int(conn.get(_RKEY_INVOKE_MS) or 0)
    avg_latency_ms = round(invoke_total_ms / invoke_count) if invoke_count else 0
    minimax_429s_1m = int(conn.get(_RKEY_429) or 0)

    return {
        "queue_depth": qd,
        "busy_workers": busy_w,
        "total_workers": total_w,
        "llm_avg_latency_ms": avg_latency_ms,
        "llm_invokes_last_2m": invoke_count,
        "minimax_429s_last_1m": minimax_429s_1m,
        # Phase 6: today's token usage + estimated cost (best-effort, 0 if no turns yet).
        "llm_token_usage": collect_token_usage(),
    }
