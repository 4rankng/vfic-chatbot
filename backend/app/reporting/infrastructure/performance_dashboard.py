"""Infrastructure-backed performance dashboard queries.

Serves two numbers for the ``Hiệu suất chatbot`` admin page: the end-to-end
response-time percentiles (p50/p95) plus a bucketed trend of the same, and the
candidate-phone conversion rate over the period. Admin-only.

Latency strategy (migration 0033 + concurrent reads + Redis cache):
- The three time-windowed reads (``_response_time_percentiles``, ``_trend``,
  ``_conversion``) run concurrently via ``asyncio.gather``, each on its own
  ``AsyncSession`` (a single session is not safe for concurrent use).
- The assembled payload is cached in Redis for 30 s (``_CACHE_TTL_SECONDS``),
  matching the frontend ``staleTime``. Auth always runs before the cache lookup.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import partial
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_json, cache_set_json
from app.shared.infrastructure.db import open_background_session

# Response cache TTL — matches frontend staleTime (usePerformanceStats.ts).
_CACHE_TTL_SECONDS = 30


def _cache_key(window: str) -> str:
    return f"perf:dashboard:{window}"


# Time windows accepted via ?window= by the main dashboard. Values are timedeltas
# bound as parameters and cast to interval in SQL via (:interval)::interval. Both
# halves matter: the cast disambiguates `now() - $1` (otherwise Postgres guesses
# wrong and fails with `timestamptz >= interval`), and a timedelta lets asyncpg
# encode the parameter natively as an interval.
#
# 1m/3m/6m are calendar-approximate: 30/90/180 days.
_DASHBOARD_WINDOWS = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
}

# Time windows accepted via ?window= by the SLO dashboard. Kept separate from the
# main dashboard's windows so the SLO route's wire contract is unchanged.
_SLO_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

# Trend bucket size per window, in seconds. Keeps long windows from returning
# tens of thousands of points (approx 48 / 56 / 30 / 90 / 26 points).
_TREND_BUCKET_SECONDS = {
    "1d": 1800,  # 30 min → 48 points
    "7d": 10800,  # 3 h → 56 points
    "1m": 86400,  # 1 day → 30 points
    "3m": 86400,  # 1 day → 90 points
    "6m": 604800,  # 7 days → ~26 points
}

_END_TO_END_SQL = (
    "COALESCE((stage_timings->>'end_to_end_ms')::int, "
    "(stage_timings->>'total_ms')::int "
    "+ COALESCE((stage_timings->>'preamble_ms')::int, 0) "
    "+ COALESCE((stage_timings->>'webhook_to_pickup_ms')::int, 0))"
)


def _int(v) -> int | None:
    return int(round(v)) if v is not None else None


async def performance_dashboard(window: str) -> dict:
    interval = _DASHBOARD_WINDOWS[window]
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
    status. SLO computation reuses ``app.services.slo_service.compute_slos``;
    the ``webhook_ack`` SLO reads from a Redis sliding window sampled at webhook
    ack time (no BotRun row exists that early). Cached 30 s to match the main
    dashboard.
    """
    interval = _SLO_WINDOWS[window]
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
    """Run the dashboard reads concurrently and assemble the response payload.

    Each DB read opens its own short-lived ``AsyncSession`` (a single session
    cannot be shared across concurrent ``gather`` coroutines). The key order
    here is the wire contract the frontend maps by position.
    """
    percentiles, trend, conversion = await asyncio.gather(
        _with_session(_response_time_percentiles, interval),
        _with_session(partial(_trend, bucket_seconds=_TREND_BUCKET_SECONDS[window]), interval),
        _with_session(_conversion, interval),
    )
    return {
        "window": window,
        "response_time": {**percentiles, "trend": trend},
        "conversion": conversion,
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


async def _response_time_percentiles(db: AsyncSession, interval: timedelta) -> dict:
    """End-to-end turn latency over the window, as p50 + p95.

    End-to-end spans webhook receipt to outbound send (``_END_TO_END_SQL``).
    Returns ``None`` percentiles when no instrumented turn falls in the window.
    """
    sql = text(
        "SELECT "
        f"percentile_cont(0.50) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p50_ms, "
        f"percentile_cont(0.95) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p95_ms "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    row = (await db.execute(sql, {"interval": interval})).one_or_none()
    if row is None:
        return {"p50_ms": None, "p95_ms": None}
    return {"p50_ms": _int(row.p50_ms), "p95_ms": _int(row.p95_ms)}


async def _trend(
    db: AsyncSession, interval: timedelta, *, bucket_seconds: int
) -> list[dict]:
    """Bucketed time-series of end-to-end p95/p50 + turn counts.

    Lets the dashboard answer "did latency spike?" — unanswerable from a single
    p95 aggregate over the whole window. Buckets align to wall-clock
    ``bucket_seconds`` boundaries so adjacent windows are comparable.
    """
    sql = text(
        "SELECT to_timestamp(floor(extract(epoch from started_at)/:bucket)*:bucket) AS bucket, "
        f"percentile_cont(0.50) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p50_ms, "
        f"percentile_cont(0.95) WITHIN GROUP (ORDER BY {_END_TO_END_SQL}) AS p95_ms, "
        "COUNT(*) AS turns "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL "
        "GROUP BY 1 ORDER BY 1"
    )
    rows = (await db.execute(sql, {"interval": interval, "bucket": bucket_seconds})).all()
    return [
        {
            "bucket": r.bucket.isoformat() if r.bucket else None,
            "p50_ms": _int(r.p50_ms),
            "p95_ms": _int(r.p95_ms),
            "turns": int(r.turns),
        }
        for r in rows
    ]


async def _conversion(db: AsyncSession, interval: timedelta) -> dict:
    """Share of active candidate chats that yielded a phone number.

    Denominator: distinct conversations that received ≥1 candidate (``WORKER``)
    message in the window. Numerator: those conversations whose contact has a
    non-disavowed ``candidate_phone_evidence`` lead event inside the same window.
    """
    sql = text(
        "WITH candidate_chats AS ("
        "  SELECT DISTINCT m.conversation_id AS conversation_id "
        "  FROM messages m "
        "  WHERE m.sender = 'WORKER' AND m.created_at >= now() - (:interval)::interval"
        "), "
        "converted AS ("
        "  SELECT DISTINCT cc.conversation_id "
        "  FROM candidate_chats cc "
        "  JOIN conversations c ON c.id = cc.conversation_id "
        "  JOIN leads l ON l.contact_id = c.contact_id "
        "  JOIN lead_events le ON le.lead_id = l.id "
        "  WHERE le.event_type = 'candidate_phone_evidence' "
        "    AND COALESCE((le.payload->>'disavowed')::bool, false) = false "
        "    AND le.created_at >= now() - (:interval)::interval"
        ") "
        "SELECT (SELECT COUNT(*) FROM candidate_chats) AS candidate_chats, "
        "(SELECT COUNT(*) FROM converted) AS with_phone"
    )
    row = (await db.execute(sql, {"interval": interval})).one()
    candidate_chats = int(row.candidate_chats or 0)
    with_phone = int(row.with_phone or 0)
    rate_pct = round(with_phone / candidate_chats * 100, 1) if candidate_chats else None
    return {
        "candidate_chats": candidate_chats,
        "with_phone": with_phone,
        "rate_pct": rate_pct,
    }
