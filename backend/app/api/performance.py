"""Performance dashboard API — per-stage turn-latency metrics for the Hiệu suất panel.

Aggregates ``BotRun.stage_timings`` (captured by ``app.graph.runner.run_turn``) into
p50/p95/p99 per stage, plus by-lane/outcome counts and the slowest recent turns.
Live tiles reuse the ``/health/queue`` snapshot via ``collect_queue_health``. Admin-only.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.core.ops_health import collect_queue_health
from app.models.user import User

router = APIRouter(prefix="/admin/performance", tags=["performance"])

# Time windows accepted via ?window=. Maps to a Postgres interval literal so the
# value never reaches SQL unparameterised.
_WINDOWS = {
    "1h": "interval '1 hour'",
    "24h": "interval '24 hours'",
    "7d": "interval '7 days'",
}

# Stages surfaced in the dashboard, in display order. Each maps to a
# stage_timings JSONB key holding milliseconds.
_STAGE_KEYS = ["webhook_to_pickup", "preamble", "lead", "llm", "safety", "send", "total"]


def _int(v) -> int | None:
    return int(round(v)) if v is not None else None


@router.get("")
async def performance(
    window: str = Query("24h", pattern="^(1h|24h|7d)$"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    interval = _WINDOWS[window]
    live = await asyncio.to_thread(collect_queue_health)
    percentiles = await _percentiles(db, interval)
    by_lane, by_outcome = await _lane_outcome_counts(db, interval)
    slow_turns = await _slow_turns(db, interval)
    return {
        "window": window,
        "live": live,
        "percentiles": percentiles,
        "by_lane": by_lane,
        "by_outcome": by_outcome,
        "slow_turns": slow_turns,
    }


async def _percentiles(db: AsyncSession, interval: str) -> dict:
    # One round-trip: one percentile_cont per (stage, p). (stage_timings->>'<k>_ms')
    # is NULL when the stage was skipped (e.g. llm_ms on a fast-lane turn); the
    # ::int cast yields NULL and percentile_cont ignores NULLs per-stage, so each
    # stage is aggregated over exactly the turns that ran it.
    cols = []
    for key in _STAGE_KEYS:
        for p, alias in (("0.5", "p50"), ("0.95", "p95"), ("0.99", "p99")):
            cols.append(
                f"percentile_cont({p}) WITHIN GROUP "
                f"(ORDER BY (stage_timings->>'{key}_ms')::int) AS {key}_{alias}"
            )
    sql = (
        "SELECT " + ", ".join(cols) + " "
        "FROM bot_runs WHERE started_at >= now() - :interval AND stage_timings IS NOT NULL"
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


async def _lane_outcome_counts(db: AsyncSession, interval: str) -> tuple[dict, dict]:
    sql = (
        "SELECT stage_timings->>'lane' AS lane, outcome, COUNT(*) AS n "
        "FROM bot_runs WHERE started_at >= now() - :interval AND stage_timings IS NOT NULL "
        "GROUP BY 1, 2"
    )
    rows = (await db.execute(text(sql), {"interval": interval})).all()
    by_lane: dict = {}
    by_outcome: dict = {}
    for r in rows:
        lane = r.lane or "unknown"
        by_lane[lane] = by_lane.get(lane, 0) + int(r.n)
        outcome = r.outcome if isinstance(r.outcome, str) else getattr(r.outcome, "value", str(r.outcome))
        by_outcome[outcome] = by_outcome.get(outcome, 0) + int(r.n)
    return by_lane, by_outcome


async def _slow_turns(db: AsyncSession, interval: str) -> list[dict]:
    sql = (
        "SELECT id, conversation_id, started_at, outcome, stage_timings "
        "FROM bot_runs WHERE started_at >= now() - :interval AND stage_timings ? 'total_ms' "
        "ORDER BY (stage_timings->>'total_ms')::int DESC LIMIT 20"
    )
    rows = (await db.execute(text(sql), {"interval": interval})).all()
    out: list[dict] = []
    for r in rows:
        st = r.stage_timings or {}
        outcome = r.outcome if isinstance(r.outcome, str) else getattr(r.outcome, "value", str(r.outcome))
        out.append({
            "id": r.id,
            "conversation_id": str(r.conversation_id),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "outcome": outcome,
            "lane": st.get("lane"),
            "llm_ms": st.get("llm_ms"),
            "total_ms": st.get("total_ms"),
            "queue_depth": st.get("queue_depth"),
        })
    return out
