"""Infrastructure-backed performance dashboard queries.

Aggregates ``BotRun.stage_timings`` (captured by ``app.graph.runner.run_turn``) into
p50/p95/p99 per stage, plus by-lane/outcome counts and the slowest recent turns.
Live tiles reuse the ``/health/queue`` snapshot via ``collect_queue_health``. Admin-only.

Latency strategy (migration 0033 + concurrent reads + Redis cache):
- The nine time-windowed reads (``_percentiles``, ``_llm_call_percentiles``,
  ``_lane_outcome_counts``, ``_adapter_breakdown``, ``_slow_turns``, ``_trend``,
  ``_reliability``, ``_quality``) run concurrently via
  ``asyncio.gather``, each on its own ``AsyncSession`` (a single session is not
  safe for concurrent use). Pool ``pool_size=10`` still has headroom for 9 reads.
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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_json, cache_set_json
from app.core.ops_health import collect_queue_health
from app.shared.infrastructure.db import open_background_session

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
    "llm_queue",
    "llm_model",
    "db",
    "outbound_prepare",
    "outbound_provider",
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


async def performance_dashboard(window: str) -> dict:
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


async def performance_slos_dashboard(window: str) -> dict:
    """Latency + reliability SLOs (Tech-Lead Directive §1).

    Returns the 7 named SLOs with target + actual p50/p95 + green/amber/red
    status. SLO computation reuses ``BotRun.stage_timings`` via
    ``app.services.slo_service.compute_slos``; the ``webhook_ack`` SLO reads
    from a Redis sliding window sampled at webhook ack time (no BotRun row
    exists that early). Cached 30 s to match the main dashboard.
    """
    interval = _WINDOWS[window]
    key = _cache_key(f"slos:{window}")
    try:
        cached = await cache_get_json(key)
    except Exception:  # noqa: BLE001
        cached = None
    if cached is not None:
        return cached  # type: ignore[return-value]
    from app.services.slo_service import compute_slos

    async with open_background_session() as session:
        slos = await compute_slos(session, interval)
    payload = {"window": window, "slos": [s.to_dict() for s in slos]}
    try:
        await cache_set_json(key, payload, ttl_seconds=_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    return payload


async def _compute(interval: timedelta, window: str) -> dict:
    """Run all dashboard reads concurrently and assemble the response payload.

    Each DB read opens its own short-lived ``AsyncSession`` (a single session
    cannot be shared across concurrent ``gather`` coroutines). Queue health is a
    sync Redis call run via ``asyncio.to_thread`` and is gathered with the rest.
    """
    (
        live,
        percentiles,
        llm_call_pct,
        (by_lane, by_outcome),
        by_adapter,
        slow_turns,
        trend,
        reliability,
        quality,
    ) = await asyncio.gather(
        asyncio.to_thread(collect_queue_health),
        _with_session(_percentiles, interval),
        _with_session(_llm_call_percentiles, interval),
        _with_session(_lane_outcome_counts, interval),
        _with_session(_adapter_breakdown, interval),
        _with_session(_slow_turns, interval),
        _with_session(_trend, interval),
        _with_session(_reliability, interval),
        _with_session(_quality, interval),
    )
    percentiles.update(llm_call_pct)
    return {
        "window": window,
        "live": live,
        "percentiles": percentiles,
        "by_lane": by_lane,
        "by_outcome": by_outcome,
        "by_adapter": by_adapter,
        "slow_turns": slow_turns,
        "trend": trend,
        "reliability": reliability,
        "quality": quality,
    }
_T = TypeVar("_T")


async def _with_session(
    coro_fn: Callable[[AsyncSession, timedelta], Awaitable[_T]], interval: timedelta
) -> _T:
    """Open a short-lived session and run ``coro_fn(session, interval)``.

    Per-read sessions make ``asyncio.gather`` safe (one ``AsyncSession`` may not
    serve two concurrent operations).
    """
    async with open_background_session() as session:
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


async def _quality(db: AsyncSession, interval: timedelta) -> dict:
    """Turn-quality and token-consumption aggregates over the window.

    Complements the latency view: ``degraded_count`` (explicit flag or legacy
    throttle key) counts turns the bot served in a reduced state,
    ``retried_429_count`` counts turns that hit LLM rate limiting (the windowed
    counterpart of the 1-minute live tile), and the prompt-cache hit rate plus
    token sums expose cost/efficiency. All read from ``stage_timings`` in one
    round-trip; the cache rate is None when no turn reported the flag.
    """
    sql = text(
        "SELECT "
        "COUNT(*) FILTER (WHERE COALESCE((stage_timings->>'degraded')::bool, "
        "(stage_timings->>'throttle')::bool, false)) AS degraded_count, "
        "COUNT(*) FILTER (WHERE COALESCE((stage_timings->>'retried_429')::bool, false)) "
        "AS retried_429_count, "
        "COUNT(*) FILTER (WHERE COALESCE((stage_timings->>'system_prompt_cache_hit')::bool, false)) "
        "AS prompt_cache_hits, "
        "COUNT(*) FILTER (WHERE stage_timings ? 'system_prompt_cache_hit') AS prompt_cache_known, "
        "COALESCE(SUM((stage_timings->>'prompt_tokens')::int), 0) AS prompt_tokens_total, "
        "COALESCE(SUM((stage_timings->>'completion_tokens')::int), 0) AS completion_tokens_total, "
        "COALESCE(SUM((stage_timings->>'cached_tokens')::int), 0) AS cached_tokens_total "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    row = (await db.execute(sql, {"interval": interval})).one_or_none()
    known = int(row.prompt_cache_known or 0) if row else 0
    return {
        "degraded_count": int(row.degraded_count or 0) if row else 0,
        "retried_429_count": int(row.retried_429_count or 0) if row else 0,
        "prompt_cache_hit_rate": (
            round(100.0 * int(row.prompt_cache_hits or 0) / known, 1) if known else None
        ),
        "prompt_tokens_total": int(row.prompt_tokens_total or 0) if row else 0,
        "completion_tokens_total": int(row.completion_tokens_total or 0) if row else 0,
        "cached_tokens_total": int(row.cached_tokens_total or 0) if row else 0,
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


async def _llm_call_percentiles(db: AsyncSession, interval: timedelta) -> dict:
    """Per-LLM-call latency + per-turn call-count percentiles.

    These are conceptually distinct from the stage percentiles in ``_percentiles``:
    - ``llm_call_per`` — latency of an INDIVIDUAL model call, computed by
      unnesting ``stage_timings->'llm_call_ms'`` (a JSON array) so each element
      is one call, not one turn. A 2-call agent turn contributes 2 samples.
      This is the number that answers "is the model itself slow?" and is the
      fair comparison to the ≤10s target — unlike ``llm_model_ms``, which
      ACCUMULATES across the agent loop and so conflates "slow model" with
      "many calls".
    - ``llm_calls_per`` — how many LLM calls a single turn makes
      (p50/p95/p99 of the integer counter). Surfaces the multi-call distribution
      so the dashboard can annotate the ``llm_model`` row with "~N lượt/turn".

    Runs as its own query (set-returning ``jsonb_array_elements_text`` can't
    share the scalar percentile SELECT) and its own session (gathered
    concurrently in ``_compute``). Both keys use the ``{p50,p95,p99}`` shape and
    are merged into the ``percentiles`` dict alongside the stage keys.
    """
    # jsonb_array_elements_text yields ``text``; percentile_cont needs a numeric
    # sort expression or Postgres rejects the overload
    # (``function percentile_cont(numeric, text) does not exist``). Cast to int,
    # matching the (stage_timings->>'<k>_ms')::int convention used in _percentiles.
    sql = text(
        "SELECT "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY call_ms::int) AS llm_call_per_p50, "
        "percentile_cont(0.95) WITHIN GROUP (ORDER BY call_ms::int) AS llm_call_per_p95, "
        "percentile_cont(0.99) WITHIN GROUP (ORDER BY call_ms::int) AS llm_call_per_p99 "
        "FROM bot_runs, "
        "jsonb_array_elements_text(stage_timings->'llm_call_ms') AS call_ms "
        "WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    call_row = (await db.execute(sql, {"interval": interval})).one_or_none()
    sql2 = text(
        "SELECT "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY (stage_timings->>'llm_calls')::int) "
        "AS llm_calls_per_p50, "
        "percentile_cont(0.95) WITHIN GROUP (ORDER BY (stage_timings->>'llm_calls')::int) "
        "AS llm_calls_per_p95, "
        "percentile_cont(0.99) WITHIN GROUP (ORDER BY (stage_timings->>'llm_calls')::int) "
        "AS llm_calls_per_p99 "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    count_row = (await db.execute(sql2, {"interval": interval})).one_or_none()
    return {
        "llm_call_per": {
            "p50": _int(getattr(call_row, "llm_call_per_p50", None)) if call_row else None,
            "p95": _int(getattr(call_row, "llm_call_per_p95", None)) if call_row else None,
            "p99": _int(getattr(call_row, "llm_call_per_p99", None)) if call_row else None,
        },
        "llm_calls_per": {
            "p50": _int(getattr(count_row, "llm_calls_per_p50", None)) if count_row else None,
            "p95": _int(getattr(count_row, "llm_calls_per_p95", None)) if count_row else None,
            "p99": _int(getattr(count_row, "llm_calls_per_p99", None)) if count_row else None,
        },
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


async def _adapter_breakdown(db: AsyncSession, interval: timedelta) -> list[dict]:
    """Compare additive outbound telemetry across every channel adapter.

    Rows without adapter telemetry are historical data. They intentionally stay
    out of this comparison rather than being guessed from a legacy channel
    field, so future adapters receive the exact same measurement contract.
    """
    sql = text(
        "SELECT stage_timings->>'outbound_adapter' AS adapter, "
        "COUNT(*) AS turns, "
        "COUNT(*) FILTER (WHERE outcome = 'SENT') AS sent, "
        "COUNT(*) FILTER (WHERE outcome != 'SENT') AS unsent, "
        "percentile_cont(0.5) WITHIN GROUP "
        "(ORDER BY (stage_timings->>'outbound_provider_ms')::int) AS provider_p50_ms, "
        "percentile_cont(0.95) WITHIN GROUP "
        "(ORDER BY (stage_timings->>'outbound_provider_ms')::int) AS provider_p95_ms, "
        "percentile_cont(0.5) WITHIN GROUP "
        f"(ORDER BY {_END_TO_END_SQL}) AS end_to_end_p50_ms, "
        "percentile_cont(0.95) WITHIN GROUP "
        f"(ORDER BY {_END_TO_END_SQL}) AS end_to_end_p95_ms, "
        "COALESCE(SUM((stage_timings->>'outbound_retry_count')::int), 0) AS retry_count, "
        "COALESCE(SUM((stage_timings->>'outbound_refresh_count')::int), 0) AS refresh_count "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings ? 'outbound_adapter' GROUP BY 1 ORDER BY 1"
    )
    rows = (await db.execute(sql, {"interval": interval})).all()
    return [
        {
            "adapter": row.adapter,
            "turns": int(row.turns),
            "sent": int(row.sent),
            "unsent": int(row.unsent),
            "provider_p50_ms": _int(row.provider_p50_ms),
            "provider_p95_ms": _int(row.provider_p95_ms),
            "end_to_end_p50_ms": _int(row.end_to_end_p50_ms),
            "end_to_end_p95_ms": _int(row.end_to_end_p95_ms),
            "retry_count": int(row.retry_count),
            "refresh_count": int(row.refresh_count),
        }
        for row in rows
    ]


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
                "outbound_adapter": st.get("outbound_adapter"),
                "outbound_prepare_ms": st.get("outbound_prepare_ms"),
                "outbound_provider_ms": st.get("outbound_provider_ms"),
                "outbound_provider_attempts": st.get("outbound_provider_attempts"),
                "outbound_retry_count": st.get("outbound_retry_count"),
                "outbound_retry_ms": st.get("outbound_retry_ms"),
                "outbound_refresh_count": st.get("outbound_refresh_count"),
                "outbound_refresh_ms": st.get("outbound_refresh_ms"),
                "outbound_chunk_count": st.get("outbound_chunk_count"),
                "outbound_result": st.get("outbound_result"),
                # DB path attribution (Proposal 1): aggregate + per-call breakdown.
                "db_ms": st.get("db_ms"),
                "db_breakdown": st.get("db_breakdown"),
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
