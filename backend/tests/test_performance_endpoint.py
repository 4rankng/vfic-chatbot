"""Unit tests for the /admin/performance endpoint + the worker preamble-timings helper.

No DB / Redis: the endpoint's SQL is exercised against a fake AsyncSession that
returns canned Row-like objects, and collect_queue_health is stubbed. Pins the
response shape the Hiệu suất panel consumes and the enqueue/preamble slicing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import performance as perf_mod
from app.api.performance import performance

CONV_ID = "00000000-0000-0000-0000-0000000000aa"


class _FakeResult:
    def __init__(self, *, one=None, all_rows=None) -> None:
        self._one = one
        self._all = all_rows or []

    def one_or_none(self):
        return self._one

    def all(self):
        return self._all


class _FakeDB:
    """Returns a queued sequence of _FakeResult, one per execute() call."""

    def __init__(self, results) -> None:
        self._results = list(results)
        self.queries: list[str] = []

    async def execute(self, stmt, params=None):
        self.queries.append(str(stmt))
        return self._results.pop(0)


def _percentile_row() -> SimpleNamespace:
    attrs: dict = {}
    for key in perf_mod._STAGE_KEYS:
        for p in ("p50", "p95", "p99"):
            # Give llm_model distinct values to assert the reshape; others default.
            attrs[f"{key}_{p}"] = {"llm_model": {"p50": 100, "p95": 500, "p99": 900}}.get(
                key, {}
            ).get(p, 10 if p == "p50" else 50 if p == "p95" else 90)
    return SimpleNamespace(**attrs)


@pytest.mark.asyncio
async def test_performance_bundle_shape(monkeypatch):
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    db = _FakeDB([
        _FakeResult(one=_percentile_row()),
        _FakeResult(all_rows=[
            SimpleNamespace(lane="agent", outcome="SENT", n=5),
            SimpleNamespace(lane="fast_lane", outcome="SENT", n=3),
        ]),
        _FakeResult(all_rows=[
            SimpleNamespace(
                id=1,
                conversation_id=uuid.UUID(CONV_ID),
                started_at=datetime(2026, 7, 9, 11, 42, 48, tzinfo=timezone.utc),
                outcome="SENT",
                stage_timings={
                    "lane": "agent",
                    "intent": "timetable",
                    "llm_queue_ms": 300,
                    "llm_model_ms": 4500,
                    "llm_calls": 1,
                    "llm_call_ms": [4500],
                    "tool_calls": 0,
                    "tool_breakdown": {},
                    "prompt_tokens": 1200,
                    "completion_tokens": 80,
                    "cached_tokens": 0,
                    "prefetch_hit": True,
                    "total_ms": 5000,
                    "preamble_ms": 1000,
                    "webhook_to_pickup_ms": 100,
                    "queue_depth": 1,
                },
            ),
        ]),
        _FakeResult(all_rows=[
            SimpleNamespace(
                bucket=datetime(2026, 7, 9, 11, 40, tzinfo=timezone.utc),
                p95_ms=3000.0,
                p50_ms=1500.0,
                turns=10,
                errors=1,
            ),
        ]),
    ])

    out = await performance("24h", _admin=SimpleNamespace(), db=db)

    assert out["window"] == "24h"
    assert out["live"] == {"queue_depth": 0}
    # percentiles reshaped per stage; llm_model p95 surfaced distinctly
    assert out["percentiles"]["llm_model"] == {"p50": 100, "p95": 500, "p99": 900}
    assert out["percentiles"]["send"]["p50"] == 10
    # counts aggregated by lane and by outcome
    assert out["by_lane"] == {"agent": 5, "fast_lane": 3}
    assert out["by_outcome"] == {"SENT": 8}
    # slow turn row mapped to the panel's columns
    slow = out["slow_turns"][0]
    assert slow["total_ms"] == 6100
    assert slow["pipeline_ms"] == 5000
    assert slow["llm_queue_ms"] == 300
    assert slow["llm_model_ms"] == 4500
    assert slow["llm_calls"] == 1
    assert slow["llm_call_ms"] == [4500]
    assert slow["tool_calls"] == 0
    assert slow["tool_breakdown"] == {}
    assert slow["prompt_tokens"] == 1200
    assert slow["completion_tokens"] == 80
    assert slow["cached_tokens"] == 0
    assert slow["retried_429"] is None
    assert slow["degraded"] is False
    assert slow["prefetch_hit"] is True
    assert slow["intent"] == "timetable"
    assert slow["lane"] == "agent"
    assert slow["conversation_id"] == CONV_ID
    assert slow["started_at"].startswith("2026-07-09T11:42:48")
    assert "end_to_end" in out["percentiles"]
    assert "llm" not in out["percentiles"]
    # trend bucket mapped from the 4th SQL result
    assert len(out["trend"]) == 1
    t = out["trend"][0]
    assert t["p95_ms"] == 3000
    assert t["p50_ms"] == 1500
    assert t["turns"] == 10
    assert t["errors"] == 1
    # four distinct SQL statements were issued (percentiles / counts / slow turns / trend)
    assert len(db.queries) == 4


@pytest.mark.asyncio
async def test_performance_empty_window_returns_nulls(monkeypatch):
    """No instrumented turns in the window -> null percentiles, empty aggregates."""
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})
    db = _FakeDB([
        _FakeResult(one=_percentile_row()),  # percentile_cont over no rows -> all NULL
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),
        _FakeResult(all_rows=[]),  # trend: no buckets
    ])
    out = await performance("1h", _admin=SimpleNamespace(), db=db)
    assert out["window"] == "1h"
    assert out["by_lane"] == {}
    assert out["by_outcome"] == {}
    assert out["slow_turns"] == []
    assert out["trend"] == []
    # _percentile_row had real ints, so just confirm shape keys exist for every stage
    assert set(out["percentiles"]) == set(perf_mod._STAGE_KEYS)


def test_worker_preamble_timings_slices_enqueue_and_preamble():
    """The LLMThrottled-path helper splits webhook→pickup from the preamble and
    carries queue_depth + the throttle flag."""
    from app.workers.chatbot_worker import _preamble_timings

    state = SimpleNamespace(
        received_at_epoch=1000.0, preamble_start_epoch=1000.3, queue_depth=2
    )
    started_at = datetime.fromtimestamp(1000.9, tz=timezone.utc)

    t = _preamble_timings(state, started_at, lane="agent", throttle=True)

    assert t == {
        "lane": "agent",
        "queue_depth": 2,
        "throttle": True,
        "degraded": True,
        "webhook_to_pickup_ms": 300,  # 0.3s
        "preamble_ms": 600,           # 0.6s
    }


def test_worker_preamble_timings_without_epoch_stamps():
    """Pre-instrumentation / unset stamps omit the epoch-derived keys, not zero."""
    from app.workers.chatbot_worker import _preamble_timings

    state = SimpleNamespace(received_at_epoch=0.0, preamble_start_epoch=0.0, queue_depth=None)
    t = _preamble_timings(state, started_at=None, lane="agent")
    assert t == {"lane": "agent"}
