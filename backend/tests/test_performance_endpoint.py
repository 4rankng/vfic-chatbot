"""Unit tests for the /admin/performance endpoint + the worker preamble-timings helper.

No DB / Redis: the endpoint's SQL is exercised against a fake ``async_session``
factory whose sessions return canned Row-like objects (routed by SQL content so
the test is insensitive to ``asyncio.gather`` scheduling order), and
``collect_queue_health`` + the cache primitives are stubbed. Pins the response
shape the Hiệu suất panel consumes, the concurrent dispatch of the reads, and the
cache hit/miss/fall-through behaviour.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

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


class _RoutingSession:
    """Fake AsyncSession that dispatches ``execute(sql)`` by SQL content.

    Order-independent: each of the 5 dashboard helpers issues one query with a
    distinct SQL shape, so routing by keyword makes the test insensitive to
    ``asyncio.gather`` scheduling order (the per-read sessions may execute in any
    sequence). Records every issued statement in ``self.queries`` for assertions.
    """

    def __init__(self, routes: list[tuple[str, _FakeResult]], queries: list[str]):
        self._routes = routes
        self.queries = queries

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.queries.append(sql)
        for needle, result in self._routes:
            if needle in sql:
                return result
        raise AssertionError(f"no fake route matched SQL: {sql[:120]}…")


class _FakeSessionCM:
    """Async context manager yielding a ``_RoutingSession``."""

    def __init__(self, session: _RoutingSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _make_session_factory(routes: list[tuple[str, _FakeResult]]):
    """Return a no-arg factory + a shared ``queries`` list.

    Each call yields a fresh session backed by the same route table and sharing
    one ``queries`` list, mirroring the real ``async_session`` factory where each
    ``async with`` gets its own session but the pool is shared.
    """
    queries: list[str] = []

    def factory():
        return _FakeSessionCM(_RoutingSession(routes, queries))

    return factory, queries


# Route keywords — each matches exactly one helper's SQL.
# NOTE: the trend SQL also contains "percentile_cont" (for its p95/p50 buckets),
# so _ROUTE_TREND must be checked before _ROUTE_PERCENTILES in the routes list
# (see _standard_routes + the empty-window routes). Otherwise the trend query
# would incorrectly match the percentiles route. The same applies to the two
# llm_call percentile queries (both contain percentile_cont).
_ROUTE_PERCENTILES = "percentile_cont"
_ROUTE_LANE_OUTCOME = "GROUP BY 1, 2"
_ROUTE_SLOW_TURNS = "LIMIT 20"
_ROUTE_TREND = "to_timestamp"
_ROUTE_RELIABILITY = "messages m"
_ROUTE_LLM_CALL_LATENCY = "jsonb_array_elements_text"
_ROUTE_LLM_CALL_COUNT = "llm_calls_per_p50"


def _percentile_row() -> SimpleNamespace:
    attrs: dict = {}
    for key in perf_mod._STAGE_KEYS:
        for p in ("p50", "p95", "p99"):
            # Give llm_model distinct values to assert the reshape; others default.
            attrs[f"{key}_{p}"] = {"llm_model": {"p50": 100, "p95": 500, "p99": 900}}.get(
                key, {}
            ).get(p, 10 if p == "p50" else 50 if p == "p95" else 90)
    return SimpleNamespace(**attrs)


def _standard_routes() -> list[tuple[str, _FakeResult]]:
    """Canned results for the five dashboard reads.

    Order matters: routes are matched in list order, so the most-specific
    keywords come first. In particular ``_percentiles`` and ``_trend`` both
    contain ``percentile_cont``, so ``_trend`` (matched on ``to_timestamp``)
    must precede ``_percentiles`` (matched on the now-leftover
    ``percentile_cont``).
    """
    return [
        (
            _ROUTE_RELIABILITY,
            _FakeResult(one=SimpleNamespace(send_unknown=2, suppressed=5, failed=1)),
        ),
        (
            _ROUTE_TREND,
            _FakeResult(
                all_rows=[
                    SimpleNamespace(
                        bucket=datetime(2026, 7, 9, 11, 40, tzinfo=timezone.utc),
                        p95_ms=3000.0,
                        p50_ms=1500.0,
                        turns=10,
                        errors=1,
                    ),
                ]
            ),
        ),
        (
            _ROUTE_SLOW_TURNS,
            _FakeResult(
                all_rows=[
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
                            "db_ms": 150,
                            "db_breakdown": {"claim_send": 90, "record_bot_outcome": 60},
                            "model_tier": "primary",
                            "system_prompt_cache_hit": True,
                        },
                    ),
                ]
            ),
        ),
        (
            _ROUTE_LANE_OUTCOME,
            _FakeResult(
                all_rows=[
                    SimpleNamespace(lane="agent", outcome="SENT", n=5),
                    SimpleNamespace(lane="fast_lane", outcome="SENT", n=3),
                ]
            ),
        ),
        (
            _ROUTE_LLM_CALL_LATENCY,
            _FakeResult(
                one=SimpleNamespace(
                    llm_call_per_p50=4000, llm_call_per_p95=7000, llm_call_per_p99=9000
                )
            ),
        ),
        (
            _ROUTE_LLM_CALL_COUNT,
            _FakeResult(
                one=SimpleNamespace(llm_calls_per_p50=1, llm_calls_per_p95=2, llm_calls_per_p99=3)
            ),
        ),
        (_ROUTE_PERCENTILES, _FakeResult(one=_percentile_row())),
    ]


def _install_compute_stubs(monkeypatch, routes=None) -> SimpleNamespace:
    """Patch ``async_session`` + queue health + force cache miss.

    Returns a namespace with ``.queries`` (issued SQL strings) and ``.captured``
    (what ``cache_set_json`` was called with) for assertions.
    """
    factory, queries = _make_session_factory(routes if routes is not None else _standard_routes())
    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    # Force cache miss so _compute runs.
    async def _miss(_key):
        return None

    monkeypatch.setattr(perf_mod, "cache_get_json", _miss)
    captured: dict[str, Any] = {}

    async def _set(key, value, ttl_seconds):
        captured["key"] = key
        captured["value"] = value
        captured["ttl"] = ttl_seconds

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)
    return SimpleNamespace(queries=queries, captured=captured)


@pytest.mark.asyncio
async def test_performance_bundle_shape(monkeypatch):
    stubs = _install_compute_stubs(monkeypatch)
    queries = stubs.queries

    out = await performance("24h", _admin=SimpleNamespace())

    assert out["window"] == "24h"
    assert out["live"] == {"queue_depth": 0}
    # percentiles reshaped per stage; llm_model p95 surfaced distinctly
    assert out["percentiles"]["llm_model"] == {"p50": 100, "p95": 500, "p99": 900}
    assert out["percentiles"]["send"]["p50"] == 10
    # Per-LLM-call latency (unnested llm_call_ms) + call-count distribution.
    # Distinct from llm_model, which ACCUMULATES across the agent loop; these
    # answer "is one model call slow?" (llm_call_per) and "how many calls per
    # turn?" (llm_calls_per) — together they decompose llm_model into its two
    # factors (per-call latency × call count).
    assert out["percentiles"]["llm_call_per"] == {"p50": 4000, "p95": 7000, "p99": 9000}
    assert out["percentiles"]["llm_calls_per"] == {"p50": 1, "p95": 2, "p99": 3}
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
    # DB path attribution (Proposal 1): db_ms + per-call breakdown surfaced.
    assert slow["db_ms"] == 150
    assert slow["db_breakdown"] == {"claim_send": 90, "record_bot_outcome": 60}
    # Model tier + cache hit (Proposal 3).
    assert slow["model_tier"] == "primary"
    assert slow["system_prompt_cache_hit"] is True
    # Dark time (Proposal 1): total_ms (5000) minus measured stages
    # (llm_queue 300 + llm_model 4500 + db 150) = 50ms unaccounted.
    assert slow["dark_time_ms"] == 50
    assert "end_to_end" in out["percentiles"]
    assert "llm" not in out["percentiles"]
    assert "safety" not in out["percentiles"]  # stale stage removed
    # New stages in the percentile chart.
    assert "db" in out["percentiles"]
    assert "faq_bypass" in out["percentiles"]
    # trend bucket mapped from the trend SQL result
    assert len(out["trend"]) == 1
    t = out["trend"][0]
    assert t["p95_ms"] == 3000
    assert t["p50_ms"] == 1500
    assert t["turns"] == 10
    assert t["errors"] == 1
    # seven distinct SQL statements issued (stage percentiles / llm_call latency
    # unnest / llm_call count / lane-outcome counts / slow turns / trend / reliability)
    assert len(queries) == 7
    # reliability section: SEND_UNKNOWN + suppressed + failed counts.
    assert out["reliability"]["send_unknown_count"] == 2
    assert out["reliability"]["suppressed_count"] == 5
    assert out["reliability"]["failed_count"] == 1
    reliability_query = next(query for query in queries if _ROUTE_RELIABILITY in query)
    # This query must run before migration 0030 adds SEND_UNKNOWN to the enum.
    # Casting to text makes the dashboard deploy-safe during a rolling migration.
    assert "m.delivery_status::text = 'SEND_UNKNOWN'" in reliability_query
    # Phase 4: cache was written with the expected key + TTL.
    captured = stubs.captured
    assert captured["key"] == "perf:dashboard:24h"
    assert captured["ttl"] == 30
    assert captured["value"] == out


@pytest.mark.asyncio
async def test_llm_call_latency_sql_casts_call_ms_to_numeric(monkeypatch):
    """Regression for production 500: percentile_cont over jsonb_array_elements_text.

    ``jsonb_array_elements_text`` returns ``text``, but ``percentile_cont`` needs a
    numeric sort expression. Without an explicit cast Postgres rejects the function
    overload with ``function percentile_cont(numeric, text) does not exist`` (HTTP
    500 on every cache miss). The fake-session harness can't catch this because it
    routes by SQL keyword and never asks Postgres to compile the statement — so pin
    the SQL shape directly: the emitted statement must cast ``call_ms`` to numeric.
    """
    stubs = _install_compute_stubs(monkeypatch)
    await performance("24h", _admin=SimpleNamespace())

    latency_query = next(
        q for q in stubs.queries if _ROUTE_LLM_CALL_LATENCY in q
    )
    # Every percentile_cont in this query must ORDER BY call_ms::int (or ::numeric).
    # The buggy form was `ORDER BY call_ms` — bare text, rejected by Postgres.
    assert "ORDER BY call_ms::int" in latency_query, latency_query
    assert "ORDER BY call_ms)" not in latency_query, latency_query


@pytest.mark.asyncio
async def test_performance_empty_window_returns_nulls(monkeypatch):
    """No instrumented turns in the window -> null percentiles, empty aggregates."""
    routes = [
        (
            _ROUTE_LLM_CALL_LATENCY,
            _FakeResult(one=None),
        ),  # no llm_call_ms rows -> one_or_none() returns None
        (
            _ROUTE_LLM_CALL_COUNT,
            _FakeResult(one=None),
        ),  # no llm_calls rows -> one_or_none() returns None
        (
            _ROUTE_PERCENTILES,
            _FakeResult(one=_percentile_row()),
        ),  # percentile_cont over no rows -> all NULL
        (_ROUTE_LANE_OUTCOME, _FakeResult(all_rows=[])),
        (_ROUTE_SLOW_TURNS, _FakeResult(all_rows=[])),
        (_ROUTE_TREND, _FakeResult(all_rows=[])),  # trend: no buckets
        (
            _ROUTE_RELIABILITY,
            _FakeResult(one=SimpleNamespace(send_unknown=0, suppressed=0, failed=0)),
        ),
    ]
    _install_compute_stubs(monkeypatch, routes=routes)

    out = await performance("1h", _admin=SimpleNamespace())
    assert out["window"] == "1h"
    assert out["by_lane"] == {}
    assert out["by_outcome"] == {}
    assert out["slow_turns"] == []
    assert out["trend"] == []
    assert out["reliability"] == {"send_unknown_count": 0, "suppressed_count": 0, "failed_count": 0}
    # _percentile_row had real ints, so just confirm shape keys exist for every stage
    # (the llm_call extras are merged in separately — asserted just below).
    assert set(perf_mod._STAGE_KEYS).issubset(out["percentiles"])
    # llm_call extras return null percentiles when there are no turns.
    assert out["percentiles"]["llm_call_per"] == {"p50": None, "p95": None, "p99": None}
    assert out["percentiles"]["llm_calls_per"] == {"p50": None, "p95": None, "p99": None}


@pytest.mark.asyncio
async def test_performance_cache_hit_short_circuits(monkeypatch):
    """Cache hit returns the cached payload and skips all DB queries."""
    cached_payload = {
        "window": "24h",
        "live": {"queue_depth": 0},
        "percentiles": {},
        "by_lane": {},
        "by_outcome": {},
        "slow_turns": [],
        "trend": [],
        "reliability": {"send_unknown_count": 0, "suppressed_count": 0, "failed_count": 0},
    }
    factory, queries = _make_session_factory(_standard_routes())
    # Even though the factory is installed, a cache hit should never touch it.
    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    async def _hit(_key):
        return cached_payload

    monkeypatch.setattr(perf_mod, "cache_get_json", _hit)
    set_called = False

    async def _set(_key, _value, _ttl):
        nonlocal set_called
        set_called = True

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    out = await performance("24h", _admin=SimpleNamespace())

    assert out is cached_payload
    assert queries == []  # no DB read ran on the hit path
    assert set_called is False  # cache_set must not run on a hit


@pytest.mark.asyncio
async def test_performance_cache_hit_preserves_key_order(monkeypatch):
    """Plan criterion: cache hit serves identical key order, not just key set.

    The frontend maps positions, so a reordered dict would silently break the
    panel. Pins the exact insertion order produced by ``_compute``.
    """
    expected_keys = [
        "window",
        "live",
        "percentiles",
        "by_lane",
        "by_outcome",
        "slow_turns",
        "trend",
        "reliability",
    ]
    cached_payload = {
        k: {} if not isinstance(k, str) or k in ("slow_turns", "trend") else None
        for k in expected_keys
    }
    cached_payload["window"] = "24h"
    cached_payload["slow_turns"] = []
    cached_payload["trend"] = []
    factory, queries = _make_session_factory(_standard_routes())
    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    async def _hit(_key):
        return cached_payload

    monkeypatch.setattr(perf_mod, "cache_get_json", _hit)

    async def _set(_key, _value, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    out = await performance("24h", _admin=SimpleNamespace())

    assert list(out.keys()) == expected_keys
    assert queries == []


@pytest.mark.asyncio
async def test_performance_cache_miss_populates_cache(monkeypatch):
    """Cache miss computes the payload and writes it under the window-scoped key."""
    stubs = _install_compute_stubs(monkeypatch)

    out = await performance("7d", _admin=SimpleNamespace())
    captured = stubs.captured
    assert captured["key"] == "perf:dashboard:7d"
    assert captured["ttl"] == 30
    assert captured["value"] == out


@pytest.mark.asyncio
async def test_performance_cache_failure_falls_through(monkeypatch):
    """If cache_get_json raises, the endpoint still computes and returns correctly.

    ``cache.py``'s helpers swallow exceptions and return None, but the handler
    must remain correct even if a different stub raises — the compute path is
    the source of truth and must run regardless of cache state.
    """
    factory, _ = _make_session_factory(_standard_routes())
    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    async def _raises(_key):
        raise RuntimeError("redis down")

    monkeypatch.setattr(perf_mod, "cache_get_json", _raises)

    async def _noop(_key, _value, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _noop)

    out = await performance("24h", _admin=SimpleNamespace())
    # Compute path ran and produced a well-formed payload.
    assert out["window"] == "24h"
    assert out["live"] == {"queue_depth": 0}
    assert out["percentiles"]["llm_model"]["p95"] == 500
    assert out["reliability"]["send_unknown_count"] == 2


@pytest.mark.asyncio
async def test_performance_cache_hit_serves_falsy_value(monkeypatch):
    """A cached falsy-but-not-None value (e.g. ``{}``) is served, not recomputed.

    Pins the handler's ``if cached is not None`` check against a future
    regression to ``if cached`` (which would silently recompute on empty payloads).
    """
    factory, queries = _make_session_factory(_standard_routes())
    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    async def _hit(_key):
        return {}  # falsy but not None

    monkeypatch.setattr(perf_mod, "cache_get_json", _hit)

    async def _set(_key, _value, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    out = await performance("24h", _admin=SimpleNamespace())

    assert out == {}  # the falsy cached value was served verbatim
    assert queries == []  # compute did not run


@pytest.mark.asyncio
async def test_performance_queries_dispatched_concurrently(monkeypatch):
    """The five DB reads run concurrently via asyncio.gather, not sequentially.

    Proves overlap: each read holds an in-flight slot for a short sleep; if the
    reads were sequential the max concurrency would be 1, but gather makes it ≥ 2.
    """
    inflight = 0
    max_inflight = 0

    class _ConcurrencySession:
        async def execute(self, stmt, params=None):
            nonlocal inflight, max_inflight
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            try:
                # Yield control so sibling gather tasks can enter their execute.
                await asyncio.sleep(0)
            finally:
                inflight -= 1
            # Route by SQL content so the payload still assembles correctly.
            sql = str(stmt)
            if _ROUTE_PERCENTILES in sql:
                return _FakeResult(one=_percentile_row())
            if _ROUTE_LANE_OUTCOME in sql:
                return _FakeResult(
                    all_rows=[
                        SimpleNamespace(lane="agent", outcome="SENT", n=1),
                    ]
                )
            if _ROUTE_SLOW_TURNS in sql:
                return _FakeResult(all_rows=[])
            if _ROUTE_TREND in sql:
                return _FakeResult(all_rows=[])
            if _ROUTE_RELIABILITY in sql:
                return _FakeResult(one=SimpleNamespace(send_unknown=0, suppressed=0, failed=0))
            raise AssertionError(f"unmatched SQL: {sql[:80]}")

    class _CM:
        async def __aenter__(self):
            return _ConcurrencySession()

        async def __aexit__(self, *exc):
            return False

    def factory():
        return _CM()

    monkeypatch.setattr(perf_mod, "async_session", factory)
    monkeypatch.setattr(perf_mod, "collect_queue_health", lambda: {"queue_depth": 0})

    async def _miss(_key):
        return None

    monkeypatch.setattr(perf_mod, "cache_get_json", _miss)

    async def _set(_k, _v, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    await performance("24h", _admin=SimpleNamespace())

    # gather ran ≥ 2 reads in flight simultaneously — sequential would be 1.
    assert max_inflight >= 2, f"reads were not concurrent (max_inflight={max_inflight})"


def test_worker_preamble_timings_slices_enqueue_and_preamble():
    """The LLMThrottled-path helper splits webhook→pickup from the preamble and
    carries queue_depth + the throttle flag."""
    from app.workers.chatbot_worker import _preamble_timings

    state = SimpleNamespace(received_at_epoch=1000.0, preamble_start_epoch=1000.3, queue_depth=2)
    started_at = datetime.fromtimestamp(1000.9, tz=timezone.utc)

    t = _preamble_timings(state, started_at, lane="agent", throttle=True)

    assert t == {
        "lane": "agent",
        "queue_depth": 2,
        "throttle": True,
        "degraded": True,
        "webhook_to_pickup_ms": 300,  # 0.3s
        "preamble_ms": 600,  # 0.6s
    }


def test_worker_preamble_timings_without_epoch_stamps():
    """Pre-instrumentation / unset stamps omit the epoch-derived keys, not zero."""
    from app.workers.chatbot_worker import _preamble_timings

    state = SimpleNamespace(received_at_epoch=0.0, preamble_start_epoch=0.0, queue_depth=None)
    t = _preamble_timings(state, started_at=None, lane="agent")
    assert t == {"lane": "agent"}
