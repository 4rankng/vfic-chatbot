"""Performance dashboard API — per-stage turn-latency metrics for the Hiệu suất panel.

Aggregates ``BotRun.stage_timings`` (captured by ``app.graph.runner.run_turn``) into
p50/p95/p99 per stage, plus by-lane/outcome counts and the slowest recent turns.
Live tiles reuse the ``/health/queue`` snapshot via ``collect_queue_health``. Admin-only.

Latency strategy (migration 0033 + concurrent reads + Redis cache):
- The five time-windowed reads (``_percentiles``, ``_lane_outcome_counts``,
  ``_slow_turns``, ``_trend``, ``_reliability``) run concurrently via
  ``asyncio.gather``, each on its own ``AsyncSession`` (a single session is not
  safe for concurrent use). Pool ``pool_size=10`` has ample headroom for 5 reads.
- The assembled payload is cached in Redis for 30 s (``_CACHE_TTL_SECONDS``),
  matching the frontend ``staleTime``. Auth always runs before the cache lookup.
- Cache tradeoff: on a hit, the ``live`` tile (queue depth / worker saturation)
  is served from the 30 s-old snapshot rather than re-read from Redis. This is
  acceptable for an admin trends view and matches the frontend's existing
  ``staleTime: 30s`` treatment of the whole payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.cache import cache_get_json, cache_set_json
from app.core.db import async_session
from app.core.ops_health import collect_queue_health
from app.models.user import User

router = APIRouter(prefix="/admin/performance", tags=["performance"])

# Response cache TTL — matches frontend staleTime (usePerformanceStats.ts).
_CACHE_TTL_SECONDS = 30


def _cache_key(window: str) -> str:
    return f"perf:dashboard:{window}"


# Time windows accepted via ?window=. Values are timedeltas bound as parameters
# and cast to interval in SQL via (:interval)::interval. Both halves matter:
# the cast disambiguates `now() - $1` (otherwise Postgres guesses wrong and
# fails with `timestamptz >= interval`), and a timedelta lets asyncpg encode
# the parameter natively as an interval.
_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

# Stages surfaced in the dashboard, in display order. Each maps to a
# stage_timings JSONB key holding milliseconds.
_STAGE_KEYS = [
    "webhook_to_pickup",
    "preamble",
    "lead",
    "system_prompt",
    "faq_bypass",
    "llm_queue",
    "llm_model",
    "db",
    "send",
    "total",
    "end_to_end",
]

_END_TO_END_SQL = (
    "COALESCE((stage_timings->>'end_to_end_ms')::int, "
    "(stage_timings->>'total_ms')::int "
    "+ COALESCE((stage_timings->>'preamble_ms')::int, 0) "
    "+ COALESCE((stage_timings->>'webhook_to_pickup_ms')::int, 0))"
)


def _stage_sql(key: str) -> str:
    if key == "end_to_end":
        return _END_TO_END_SQL
    return f"(stage_timings->>'{key}_ms')::int"


def _int(v) -> int | None:
    return int(round(v)) if v is not None else None


# The intra-turn stages that sum to total_ms. dark_time_ms = total_ms - sum(these).
# When dark time spikes, the next timing probe goes inside the gap. Listed here
# (not computed from the full stage_timings dict) so adding a new unmeasured
# in-process computation does NOT silently inflate dark time.
_MEASURED_STAGES = (
    "lead_ms",
    "system_prompt_ms",
    "llm_queue_ms",
    "llm_model_ms",
    "llm_backoff_ms",
    "tool_ms",
    "send_ms",
    "db_ms",
    "faq_bypass_ms",
)


def _dark_time_ms(st: dict) -> int | None:
    """total_ms minus the sum of every measured intra-turn stage.

    Returns None when total_ms itself is absent (lane skipped timing). A
    consistently low value (<5% of total_ms) means instrumentation is
    sufficient; a spike marks the spot to add the next probe.
    """
    total = st.get("total_ms")
    if total is None:
        return None
    measured = sum(int(st.get(k) or 0) for k in _MEASURED_STAGES)
    return max(0, int(total) - measured)


@router.get("")
async def performance(
    window: str = Query("24h", pattern="^(1h|24h|7d)$"),
    _admin: User = Depends(require_admin),
) -> dict:
    interval = _WINDOWS[window]
    key = _cache_key(window)
    # cache_get_json/cache_set_json swallow internally, but wrap defensively so
    # a Redis outage (or a stub that raises) never breaks the dashboard — the
    # compute path is the source of truth.
    try:
        cached = await cache_get_json(key)
    except Exception:  # noqa: BLE001 — cache must never break the endpoint
        cached = None
    if cached is not None:
        return cached  # type: ignore[return-value]
    payload = await _compute(interval, window)
    try:
        await cache_set_json(key, payload, ttl_seconds=_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — cache write failure is non-fatal
        pass
    return payload


async def _compute(interval: timedelta, window: str) -> dict:
    """Run all dashboard reads concurrently and assemble the response payload.

    Each DB read opens its own short-lived ``AsyncSession`` (a single session
    cannot be shared across concurrent ``gather`` coroutines). Queue health is a
    sync Redis call run via ``asyncio.to_thread`` and is gathered with the rest.
    """
    live, percentiles, (by_lane, by_outcome), slow_turns, trend, reliability = await asyncio.gather(
        asyncio.to_thread(collect_queue_health),
        _with_session(_percentiles, interval),
        _with_session(_lane_outcome_counts, interval),
        _with_session(_slow_turns, interval),
        _with_session(_trend, interval),
        _with_session(_reliability, interval),
    )
    return {
        "window": window,
        "live": live,
        "percentiles": percentiles,
        "by_lane": by_lane,
        "by_outcome": by_outcome,
        "slow_turns": slow_turns,
        "trend": trend,
        "reliability": reliability,
    }


_T = TypeVar("_T")


async def _with_session(
    coro_fn: Callable[[AsyncSession, timedelta], Awaitable[_T]], interval: timedelta
) -> _T:
    """Open a short-lived session and run ``coro_fn(session, interval)``.

    Per-read sessions make ``asyncio.gather`` safe (one ``AsyncSession`` may not
    serve two concurrent operations).
    """
    async with async_session() as session:
        return await coro_fn(session, interval)


async def _reliability(db: AsyncSession, interval: timedelta) -> dict:
    """Delivery-reliability counters: SEND_UNKNOWN (ambiguous send) + suppressed turns.

    Surfaced separately from by_outcome because these are reliability signals, not
    lane/outcome distributions. ``send_unknown_count`` is the canary for the
    duplicate-reply window closed in Phase 1 — a spike means Zalo transport
    timeouts. ``suppressed_count`` is the human-takeover cancellation rate.
    """
    sql = text(
        "SELECT "
        "COUNT(*) FILTER (WHERE m.delivery_status::text = 'SEND_UNKNOWN') AS send_unknown, "
        "COUNT(*) FILTER (WHERE m.delivery_status::text = 'SUPPRESSED') AS suppressed, "
        "COUNT(*) FILTER (WHERE m.delivery_status::text = 'FAILED') AS failed "
        "FROM messages m "
        "JOIN bot_runs b ON b.id = m.bot_run_id "
        "WHERE b.started_at >= now() - (:interval)::interval "
        "AND m.sender = 'BOT'"
    )
    row = (await db.execute(sql, {"interval": interval})).one_or_none()
    return {
        "send_unknown_count": int(row.send_unknown or 0) if row else 0,
        "suppressed_count": int(row.suppressed or 0) if row else 0,
        "failed_count": int(row.failed or 0) if row else 0,
    }


async def _percentiles(db: AsyncSession, interval: timedelta) -> dict:
    # One round-trip: one percentile_cont per (stage, p). (stage_timings->>'<k>_ms')
    # is NULL when the stage was skipped (e.g. llm_model_ms on a fast-lane turn);
    # the ::int cast yields NULL and percentile_cont ignores NULLs per-stage, so
    # each stage is aggregated over exactly the turns that ran it.
    cols = []
    for key in _STAGE_KEYS:
        value_sql = _stage_sql(key)
        for p, alias in (("0.5", "p50"), ("0.95", "p95"), ("0.99", "p99")):
            cols.append(
                f"percentile_cont({p}) WITHIN GROUP (ORDER BY {value_sql}) AS {key}_{alias}"
            )
    sql = (
        "SELECT " + ", ".join(cols) + " "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    row = (await db.execute(text(sql), {"interval": interval})).one_or_none()
    if row is None:
        return {key: {"p50": None, "p95": None, "p99": None} for key in _STAGE_KEYS}
    return {
        key: {
            "p50": _int(getattr(row, f"{key}_p50")),
            "p95": _int(getattr(row, f"{key}_p95")),
            "p99": _int(getattr(row, f"{key}_p99")),
        }
        for key in _STAGE_KEYS
    }


async def _lane_outcome_counts(db: AsyncSession, interval: timedelta) -> tuple[dict, dict]:
    sql = (
        "SELECT stage_timings->>'lane' AS lane, outcome, COUNT(*) AS n "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL GROUP BY 1, 2"
    )
    rows = (await db.execute(text(sql), {"interval": interval})).all()
    by_lane: dict = {}
    by_outcome: dict = {}
    for r in rows:
        lane = r.lane or "unknown"
        by_lane[lane] = by_lane.get(lane, 0) + int(r.n)
        outcome = (
            r.outcome if isinstance(r.outcome, str) else getattr(r.outcome, "value", str(r.outcome))
        )
        by_outcome[outcome] = by_outcome.get(outcome, 0) + int(r.n)
    return by_lane, by_outcome


async def _slow_turns(db: AsyncSession, interval: timedelta) -> list[dict]:
    sql = (
        "SELECT id, conversation_id, started_at, outcome, stage_timings "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings ? 'total_ms' "
        f"ORDER BY {_END_TO_END_SQL} DESC LIMIT 20"
    )
    rows = (await db.execute(text(sql), {"interval": interval})).all()
    out: list[dict] = []
    for r in rows:
        st = r.stage_timings or {}
        pipeline_ms = st.get("total_ms")
        end_to_end_ms = st.get("end_to_end_ms")
        if end_to_end_ms is None and pipeline_ms is not None:
            end_to_end_ms = (
                int(pipeline_ms)
                + int(st.get("preamble_ms") or 0)
                + int(st.get("webhook_to_pickup_ms") or 0)
            )
        outcome = (
            r.outcome if isinstance(r.outcome, str) else getattr(r.outcome, "value", str(r.outcome))
        )
        # degraded covers both the new explicit flag and the legacy throttle key.
        degraded = bool(st.get("degraded") or st.get("throttle"))
        out.append(
            {
                "id": r.id,
                "conversation_id": str(r.conversation_id),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "outcome": outcome,
                "lane": st.get("lane"),
                "intent": st.get("intent"),
                "llm_queue_ms": st.get("llm_queue_ms"),
                "llm_model_ms": st.get("llm_model_ms"),
                "llm_backoff_ms": st.get("llm_backoff_ms"),
                "llm_calls": st.get("llm_calls"),
                "llm_call_ms": st.get("llm_call_ms"),
                "tool_calls": st.get("tool_calls"),
                "tool_ms": st.get("tool_ms"),
                "tool_breakdown": st.get("tool_breakdown"),
                "prompt_tokens": st.get("prompt_tokens"),
                "completion_tokens": st.get("completion_tokens"),
                "cached_tokens": st.get("cached_tokens"),
                "retried_429": st.get("retried_429"),
                "degraded": degraded,
                "prefetch_hit": st.get("prefetch_hit"),
                "pipeline_ms": pipeline_ms,
                "total_ms": end_to_end_ms,
                "queue_depth": st.get("queue_depth"),
                # DB path attribution (Proposal 1): aggregate + per-call breakdown.
                "db_ms": st.get("db_ms"),
                "db_breakdown": st.get("db_breakdown"),
                # FAQ bypass latency (Proposal 2) — null when the bypass cascade
                # didn't run (agent lane or fast lane).
                "faq_bypass_ms": st.get("faq_bypass_ms"),
                # Model tier + system-prompt cache hit (Proposal 3).
                "model_tier": st.get("model_tier"),
                "system_prompt_cache_hit": st.get("system_prompt_cache_hit"),
                # Dark time (Proposal 1): total_ms minus the sum of every measured
                # intra-turn stage. When this is consistently low (<5% of total_ms),
                # instrumentation is sufficient. A spike marks the exact spot to add
                # the next probe. Computed from the pipeline (post-preamble) slice.
                "dark_time_ms": _dark_time_ms(st),
            }
        )
    return out


async def _trend(db: AsyncSession, interval: timedelta) -> list[dict]:
    """5-minute bucket time-series of end-to-end p95/p50 + turn/error counts.

    Lets the dashboard answer "did latency spike?" — unanswerable from a single
    p95 aggregate over the whole window. Buckets align to wall-clock 5-min
    boundaries (floor(epoch/300)*300) so adjacent windows are comparable.
    """
    sql = text(
        "SELECT to_timestamp(floor(extract(epoch from started_at)/300)*300) AS bucket, "
        f"percentile_cont(0.95) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p95_ms, "
        f"percentile_cont(0.50) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p50_ms, "
        "COUNT(*) AS turns, "
        "COUNT(*) FILTER (WHERE outcome != 'SENT') AS errors "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL "
        "GROUP BY 1 ORDER BY 1"
    )
    rows = (await db.execute(sql, {"interval": interval})).all()
    return [
        {
            "bucket": r.bucket.isoformat() if r.bucket else None,
            "p95_ms": _int(r.p95_ms),
            "p50_ms": _int(r.p50_ms),
            "turns": int(r.turns),
            "errors": int(r.errors),
        }
        for r in rows
    ]
