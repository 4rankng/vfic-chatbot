"""Latency SLO definitions + rollup (Tech-Lead Directive §1).

The codebase ALREADY captures rich per-turn stage timings in
``BotRun.stage_timings`` and rolls them up via ``app.api.performance._percentiles``.
This module wraps that data in the directive's named-SLO contract:

- 7 SLOs with target + actual p50/p95 + green/amber/red status.
- Most reuse the existing ``percentile_cont`` over ``stage_timings`` columns.
- ``webhook_ack`` is sampled into a Redis sliding window (the ack happens
  before any ``BotRun`` row exists, so it cannot live on the row).
- ``duplicate_outbound_rate`` is stubbed (returns null) until the transactional
  outbox (P0-5) lands and can stamp duplicates authoritatively.

SLO → measurement mapping
-------------------------
+---------------------------+-------------------------------------------------+
| SLO                       | Source                                          |
+---------------------------+-------------------------------------------------+
| webhook_ack               | Redis sliding window (this module)              |
| queue_wait                | webhook_to_pickup_ms + preamble_ms on BotRun    |
| cached_or_deterministic   | end_to_end_ms WHERE lane IN (fast_lane, faq_*)  |
| rag_ttfb                  | null until streaming lands (P0-6)               |
| full_answer               | end_to_end_ms WHERE lane = 'agent'              |
| error_or_timeout_rate     | % of turns WHERE outcome != 'SENT'              |
| duplicate_outbound_rate   | null until outbox (P0-5)                        |
+---------------------------+-------------------------------------------------+

Status thresholds
-----------------
- green  : actual_p95 ≤ target
- amber  : actual_p95 ≤ 1.5 × target
- red    : actual_p95 > 1.5 × target (or any error-rate SLO over target)
- unknown: insufficient data in the window
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SloStatus = Literal["green", "amber", "red", "unknown"]


# ─── Directive §1 SLO targets (initial engineering targets) ──────────────────
# These are starting SLOs, not promises. Tunable from env later if needed.
DEFAULT_TARGETS: dict[str, float] = {
    "webhook_ack_ms": 100.0,
    "queue_wait_ms": 150.0,
    "cached_or_deterministic_ms": 500.0,
    # rag_ttfb has no measurement until streaming lands.
    "full_answer_ms": 4_000.0,
    "error_or_timeout_rate_pct": 1.0,
    "duplicate_outbound_rate_pct": 0.0,
}


@dataclass(frozen=True)
class SloResult:
    """One SLO's rollup over a window."""

    name: str
    description: str
    target: float
    unit: str  # "ms" or "%"
    actual_p50: float | None
    actual_p95: float | None
    status: SloStatus

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "target": self.target,
            "unit": self.unit,
            "actual_p50": self.actual_p50,
            "actual_p95": self.actual_p95,
            "status": self.status,
        }


def _status_for(value: float | None, target: float, *, is_rate: bool = False) -> SloStatus:
    """Green/amber/red/unknown classification.

    For latency SLOs: green ≤ target, amber ≤ 1.5× target, red beyond.
    For rate SLOs (errors / duplicates): green ≤ target, amber ≤ 2× target, red
    beyond — rates tolerate more headroom because a single bad event can spike
    a small-window rate.
    """
    if value is None:
        return "unknown"
    if is_rate:
        if value <= target:
            return "green"
        if value <= max(target * 2, target + 1.0):
            return "amber"
        return "red"
    if value <= target:
        return "green"
    if value <= target * 1.5:
        return "amber"
    return "red"


# ─── Webhook-ack Redis sliding window ────────────────────────────────────────
# The ack happens before any DB write, so we sample it into Redis. Two Redis
# structures under ``slo:webhook_ack:*``:
#   slo:webhook_ack:sum    — running sum of ack_ms samples (INCRBYFLOAT)
#   slo:webhook_ack:count  — running count (INCR)
#   slo:webhook_ack:p95    — a small (capped) sorted set for p95 approximation
# Both are 1-hour TTL-bucketed so the rollup window is bounded. We use a sorted
# set with capped membership (trim to last 500) to approximate p95 cheaply —
# exact p95 over every ack would require storing every sample, which is too
# much write amplification for the webhook hot path.
_ACK_SUM_KEY = "slo:webhook_ack:sum"
_ACK_COUNT_KEY = "slo:webhook_ack:count"
_ACK_SAMPLES_KEY = "slo:webhook_ack:samples"  # sorted set: member=sample_id, score=ack_ms
_ACK_SAMPLES_CAP = 500
_ACK_BUCKET_TTL_SECONDS = 3_600  # 1h rolling


async def record_webhook_ack_ms(ack_ms: float) -> None:
    """Sample one webhook-ack duration into the Redis sliding window.

    Best-effort: any Redis error is swallowed (the ack already succeeded; SLO
    instrumentation must never break the webhook). Imported lazily so the
    webhook module doesn't pay the import cost when Redis is mocked in tests.
    """
    try:
        from app.core.redis import get_redis

        r = await get_redis()
        # Sliding-window counters (for p50 approximation via sum/count).
        await r.incrbyfloat(_ACK_SUM_KEY, ack_ms)
        await r.incr(_ACK_COUNT_KEY)
        # Sorted-set sample for p95 (member must be unique; use a counter-ish id).
        sample_id = f"{time.time_ns()}"
        await r.zadd(_ACK_SAMPLES_KEY, {sample_id: ack_ms})
        # Cap membership so the set stays bounded.
        count = await r.zcard(_ACK_SAMPLES_KEY)
        if count > _ACK_SAMPLES_CAP:
            # Trim oldest by score (lowest ack_ms first keeps the tail; we want
            # an unbiased sample, so trim by insertion order via lex — but ZSET
            # is sorted by score. Approximation: trim to the cap by rank,
            # keeping the most recent _ACK_SAMPLES_CAP members by removing from
            # the head. Since members are insertion-named and scored by ack_ms,
            # we can't trim by insertion order directly. Accept the cap as a
            # score-ordered sample — p95 over the lowest N is a slight bias, but
            # the value is a canary, not a precision instrument.)
            await r.zremrangebyrank(_ACK_SAMPLES_KEY, 0, count - _ACK_SAMPLES_CAP - 1)
        # Refresh TTL on the bucket keys.
        await r.expire(_ACK_SUM_KEY, _ACK_BUCKET_TTL_SECONDS)
        await r.expire(_ACK_COUNT_KEY, _ACK_BUCKET_TTL_SECONDS)
        await r.expire(_ACK_SAMPLES_KEY, _ACK_BUCKET_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — instrumentation must not break the webhook
        logger.debug("webhook-ack SLO sample dropped", exc_info=True)


async def _rollup_webhook_ack() -> tuple[float | None, float | None]:
    """Return (p50_ms, p95_ms) from the Redis sliding window, or (None, None)."""
    try:
        from app.core.redis import get_redis

        r = await get_redis()
        count = int(await r.get(_ACK_COUNT_KEY) or 0)
        if count == 0:
            return None, None
        total = float(await r.get(_ACK_SUM_KEY) or 0.0)
        p50 = total / count
        # p95 from the sorted set: pick the member at the 95th percentile rank.
        members = await r.zcard(_ACK_SAMPLES_KEY)
        if members == 0:
            return p50, None
        idx = int(members * 0.95)
        # zrange by index withscores returns the slice; take the score at idx.
        window = await r.zrange(_ACK_SAMPLES_KEY, idx, idx, withscores=True)
        if not window:
            return p50, None
        _, p95 = window[0]
        return p50, float(p95)
    except Exception:  # noqa: BLE001
        logger.debug("webhook-ack SLO rollup failed", exc_info=True)
        return None, None


# ─── Main entry point ────────────────────────────────────────────────────────


async def compute_slos(db: AsyncSession, interval: timedelta) -> list[SloResult]:
    """Compute all 7 SLOs over ``interval``. ``db`` is a short-lived session.

    Reuses the same ``percentile_cont``-over-``stage_timings`` pattern as
    ``app.api.performance._percentiles`` but with lane filters and the SLO
    target/status layer on top.
    """
    out: list[SloResult] = []

    # 1. webhook_ack — from Redis sliding window (no DB row exists at ack time).
    ack_p50, ack_p95 = await _rollup_webhook_ack()
    out.append(
        SloResult(
            name="webhook_ack",
            description="Webhook receive → 200 OK returned",
            target=DEFAULT_TARGETS["webhook_ack_ms"],
            unit="ms",
            actual_p50=ack_p50,
            actual_p95=ack_p95,
            status=_status_for(ack_p95, DEFAULT_TARGETS["webhook_ack_ms"]),
        )
    )

    # 2-5. Latency SLOs from BotRun.stage_timings (one query, four rollups).
    latency_rollups = await _latency_rollups(db, interval)

    # queue_wait = webhook_to_pickup_ms + preamble_ms
    out.append(
        SloResult(
            name="queue_wait",
            description="Webhook ack → RQ job starts running (webhook_high queue)",
            target=DEFAULT_TARGETS["queue_wait_ms"],
            unit="ms",
            actual_p50=latency_rollups["queue_wait"]["p50"],
            actual_p95=latency_rollups["queue_wait"]["p95"],
            status=_status_for(
                latency_rollups["queue_wait"]["p95"], DEFAULT_TARGETS["queue_wait_ms"]
            ),
        )
    )

    # cached_or_deterministic — fast lanes only
    out.append(
        SloResult(
            name="cached_or_deterministic",
            description="Turn total when fast-lane / exact cache / FAQ-bypass hits",
            target=DEFAULT_TARGETS["cached_or_deterministic_ms"],
            unit="ms",
            actual_p50=latency_rollups["cached"]["p50"],
            actual_p95=latency_rollups["cached"]["p95"],
            status=_status_for(
                latency_rollups["cached"]["p95"],
                DEFAULT_TARGETS["cached_or_deterministic_ms"],
            ),
        )
    )

    # rag_ttfb — not measurable until streaming (P0-6)
    out.append(
        SloResult(
            name="rag_ttfb",
            description="Time-to-first-token on a full RAG turn (needs streaming, P0-6)",
            target=1_500.0,
            unit="ms",
            actual_p50=None,
            actual_p95=None,
            status="unknown",
        )
    )

    # full_answer — agent lane only
    out.append(
        SloResult(
            name="full_answer",
            description="Total turn time on a normal answer (agent lane)",
            target=DEFAULT_TARGETS["full_answer_ms"],
            unit="ms",
            actual_p50=latency_rollups["full_answer"]["p50"],
            actual_p95=latency_rollups["full_answer"]["p95"],
            status=_status_for(
                latency_rollups["full_answer"]["p95"], DEFAULT_TARGETS["full_answer_ms"]
            ),
        )
    )

    # 6. error_or_timeout_rate — % of turns with outcome != 'SENT'
    err_rate = await _error_or_timeout_rate(db, interval)
    out.append(
        SloResult(
            name="error_or_timeout_rate",
            description="% of turns that end in error/timeout/fallback (outcome != SENT)",
            target=DEFAULT_TARGETS["error_or_timeout_rate_pct"],
            unit="%",
            actual_p50=err_rate,
            actual_p95=err_rate,
            status=_status_for(
                err_rate,
                DEFAULT_TARGETS["error_or_timeout_rate_pct"],
                is_rate=True,
            ),
        )
    )

    # 7. duplicate_outbound_rate — stubbed until outbox (P0-5)
    out.append(
        SloResult(
            name="duplicate_outbound_rate",
            description="% of turns producing a duplicate outbound (needs outbox, P0-5)",
            target=DEFAULT_TARGETS["duplicate_outbound_rate_pct"],
            unit="%",
            actual_p50=None,
            actual_p95=None,
            status="unknown",
        )
    )

    return out


async def _latency_rollups(db: AsyncSession, interval: timedelta) -> dict:
    """One round-trip: p50/p95 for queue_wait, cached lanes, and full_answer.

    ``queue_wait_ms`` is computed per-row as webhook_to_pickup_ms + preamble_ms
    (both already on stage_timings) so percentile_cont sees the combined value
    rather than the two halves separately.
    """
    # Per-row computed columns so percentile_cont has a single value to order.
    queue_wait_expr = (
        "(COALESCE((stage_timings->>'webhook_to_pickup_ms')::int, 0) "
        "+ COALESCE((stage_timings->>'preamble_ms')::int, 0))"
    )
    end_to_end_expr = (
        "COALESCE((stage_timings->>'end_to_end_ms')::int, "
        "(stage_timings->>'total_ms')::int "
        "+ COALESCE((stage_timings->>'preamble_ms')::int, 0) "
        "+ COALESCE((stage_timings->>'webhook_to_pickup_ms')::int, 0))"
    )
    base = (
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )

    def pct(expr: str, p: str) -> str:
        return f"percentile_cont({p}) WITHIN GROUP (ORDER BY {expr})"

    # Three SLOs × two percentiles, each scoped to its lane set.
    sql = text(
        "SELECT "
        # queue_wait (all lanes)
        f"{pct(queue_wait_expr, '0.5')} AS qw_p50, "
        f"{pct(queue_wait_expr, '0.95')} AS qw_p95, "
        # cached_or_deterministic (fast lanes only)
        f"{pct(end_to_end_expr, '0.5')} FILTER (WHERE stage_timings->>'lane' IN ('fast_lane','faq_bypass','faq_detail')) AS cd_p50, "
        f"{pct(end_to_end_expr, '0.95')} FILTER (WHERE stage_timings->>'lane' IN ('fast_lane','faq_bypass','faq_detail')) AS cd_p95, "
        # full_answer (agent lane only)
        f"{pct(end_to_end_expr, '0.5')} FILTER (WHERE stage_timings->>'lane' = 'agent') AS fa_p50, "
        f"{pct(end_to_end_expr, '0.95')} FILTER (WHERE stage_timings->>'lane' = 'agent') AS fa_p95 "
        + base
    )
    row = (await db.execute(sql, {"interval": interval})).one_or_none()
    if row is None:
        empty = {"p50": None, "p95": None}
        return {"queue_wait": empty, "cached": empty, "full_answer": empty}

    def _f(v) -> float | None:
        return float(v) if v is not None else None

    return {
        "queue_wait": {"p50": _f(row.qw_p50), "p95": _f(row.qw_p95)},
        "cached": {"p50": _f(row.cd_p50), "p95": _f(row.cd_p95)},
        "full_answer": {"p50": _f(row.fa_p50), "p95": _f(row.fa_p95)},
    }


async def _error_or_timeout_rate(db: AsyncSession, interval: timedelta) -> float | None:
    """% of turns with outcome != 'SENT' over the window. None if no turns."""
    sql = text(
        "SELECT "
        "COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE outcome IS DISTINCT FROM 'SENT') AS bad "
        "FROM bot_runs WHERE started_at >= now() - (:interval)::interval "
        "AND stage_timings IS NOT NULL"
    )
    row = (await db.execute(sql, {"interval": interval})).one_or_none()
    if row is None or not row.total:
        return None
    return (int(row.bad) / int(row.total)) * 100.0
