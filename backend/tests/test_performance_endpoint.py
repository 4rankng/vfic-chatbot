"""Unit tests for the /admin/performance endpoint + the worker preamble-timings helper.

No DB / Redis: the endpoint's SQL is exercised against a fake session factory
whose sessions return canned Row-like objects (routed by SQL content so the test
is insensitive to ``asyncio.gather`` scheduling order), and the cache primitives
are stubbed. Pins the two-metric response shape the Hiệu suất panel consumes,
the concurrent dispatch of the reads, the per-window trend bucket binding, and
the cache hit/miss/fall-through behaviour.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_dependencies import require_admin
from app.api.performance import performance, router
from app.reporting.infrastructure import performance_dashboard as perf_mod


class _FakeResult:
    def __init__(self, *, one=None, all_rows=None) -> None:
        self._one = one
        self._all = all_rows or []

    def one(self):
        assert self._one is not None, "fake result had no single row"
        return self._one

    def one_or_none(self):
        return self._one

    def all(self):
        return self._all


class _RoutingSession:
    """Fake AsyncSession that dispatches ``execute(sql)`` by SQL content.

    Order-independent: each dashboard helper issues one query with a distinct SQL
    shape, so routing by keyword makes the test insensitive to
    ``asyncio.gather`` scheduling order (the per-read sessions may execute in any
    sequence). Records every issued statement + bound params for assertions.
    """

    def __init__(self, routes: list[tuple[str, _FakeResult]], queries: list[str]):
        self._routes = routes
        self.queries = queries

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.queries.append((sql, params))
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
    """Return a no-arg factory + a shared query log.

    Each call yields a fresh session backed by the same route table and sharing
    one log, mirroring the real session factory where each ``async with`` gets
    its own session but the pool is shared.
    """
    queries: list[tuple[str, Any]] = []

    def factory():
        return _FakeSessionCM(_RoutingSession(routes, queries))

    return factory, queries


# Route keywords — each matches exactly one helper's SQL, listed in match order.
# NOTE: the trend SQL also contains "percentile_cont" (for its p50/p95 buckets),
# so _ROUTE_TREND must precede _ROUTE_PERCENTILES. The conversion CTE name
# ("candidate_chats") appears only in the conversion query, so its route goes
# first of all.
_ROUTE_CONVERSION = "candidate_chats"
_ROUTE_TREND = "to_timestamp"
_ROUTE_PERCENTILES = "percentile_cont"


def _standard_routes() -> list[tuple[str, _FakeResult]]:
    """Canned results for the three dashboard reads."""
    return [
        (
            _ROUTE_CONVERSION,
            _FakeResult(one=SimpleNamespace(candidate_chats=12, with_phone=3)),
        ),
        (
            _ROUTE_TREND,
            _FakeResult(
                all_rows=[
                    SimpleNamespace(
                        bucket=datetime(2026, 7, 9, 11, 30, tzinfo=timezone.utc),
                        p50_ms=1500.0,
                        p95_ms=3000.0,
                        turns=10,
                    ),
                    SimpleNamespace(
                        bucket=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
                        p50_ms=1200.0,
                        p95_ms=2600.0,
                        turns=6,
                    ),
                ]
            ),
        ),
        (
            _ROUTE_PERCENTILES,
            _FakeResult(one=SimpleNamespace(p50_ms=1400.0, p95_ms=2900.0)),
        ),
    ]


def _install_compute_stubs(monkeypatch, routes=None) -> SimpleNamespace:
    """Patch the session factory + force a cache miss.

    Returns a namespace with ``.queries`` (issued SQL + params) and
    ``.captured`` (what ``cache_set_json`` was called with) for assertions.
    """
    factory, queries = _make_session_factory(routes if routes is not None else _standard_routes())
    monkeypatch.setattr(perf_mod, "open_background_session", factory)

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

    out = await performance("7d", _admin=SimpleNamespace())

    # Key order is the wire contract the frontend maps.
    assert list(out.keys()) == ["window", "response_time", "conversion"]
    assert out["window"] == "7d"
    rt = out["response_time"]
    assert rt["p50_ms"] == 1400
    assert rt["p95_ms"] == 2900
    assert [row for row in rt["trend"]] == [
        {
            "bucket": "2026-07-09T11:30:00+00:00",
            "p50_ms": 1500,
            "p95_ms": 3000,
            "turns": 10,
        },
        {
            "bucket": "2026-07-09T12:00:00+00:00",
            "p50_ms": 1200,
            "p95_ms": 2600,
            "turns": 6,
        },
    ]
    assert "errors" not in rt["trend"][0]
    assert out["conversion"] == {"candidate_chats": 12, "with_phone": 3, "rate_pct": 25.0}

    # Three reads, one statement each.
    assert len(stubs.queries) == 3
    # Cache written under the window-scoped key with the frontend-matching TTL.
    assert stubs.captured["key"] == "perf:dashboard:7d"
    assert stubs.captured["ttl"] == 30
    assert stubs.captured["value"] == out
    # The conversion query filters disavowed evidence and stays inside the window.
    conversion_query = next(q for q, _ in stubs.queries if _ROUTE_CONVERSION in q)
    assert "'candidate_phone_evidence'" in conversion_query
    assert "COALESCE((le.payload->>'disavowed')::bool, false) = false" in conversion_query


@pytest.mark.asyncio
async def test_performance_conversion_rate_is_none_without_candidate_chats(monkeypatch):
    """Zero candidate chats -> rate is unknown (None), counters are still zero."""
    routes = [
        (_ROUTE_CONVERSION, _FakeResult(one=SimpleNamespace(candidate_chats=0, with_phone=0))),
        (_ROUTE_TREND, _FakeResult(all_rows=[])),
        (_ROUTE_PERCENTILES, _FakeResult(one=None)),
    ]
    _install_compute_stubs(monkeypatch, routes=routes)

    out = await performance("1d", _admin=SimpleNamespace())

    assert out["conversion"] == {"candidate_chats": 0, "with_phone": 0, "rate_pct": None}
    assert out["response_time"]["p50_ms"] is None
    assert out["response_time"]["p95_ms"] is None
    assert out["response_time"]["trend"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window", "bucket_seconds"),
    [("1d", 1800), ("7d", 10800), ("1m", 86400), ("3m", 86400), ("6m", 604800)],
)
async def test_performance_trend_bucket_follows_window(monkeypatch, window, bucket_seconds):
    """Each window binds its own bucket size so long windows stay a few dozen points."""
    stubs = _install_compute_stubs(monkeypatch)

    await performance(window, _admin=SimpleNamespace())

    trend_params = next(params for q, params in stubs.queries if _ROUTE_TREND in q)
    assert trend_params["bucket"] == bucket_seconds


@pytest.mark.asyncio
async def test_performance_cache_hit_short_circuits(monkeypatch):
    """Cache hit returns the cached payload and skips all DB queries."""
    cached_payload = {
        "window": "7d",
        "response_time": {"p50_ms": 1, "p95_ms": 2, "trend": []},
        "conversion": {"candidate_chats": 0, "with_phone": 0, "rate_pct": None},
    }
    factory, queries = _make_session_factory(_standard_routes())
    # Even though the factory is installed, a cache hit should never touch it.
    monkeypatch.setattr(perf_mod, "open_background_session", factory)

    async def _hit(_key):
        return cached_payload

    monkeypatch.setattr(perf_mod, "cache_get_json", _hit)
    set_called = False

    async def _set(_key, _value, _ttl):
        nonlocal set_called
        set_called = True

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    out = await performance("7d", _admin=SimpleNamespace())

    assert out is cached_payload
    assert queries == []  # no DB read ran on the hit path
    assert set_called is False  # cache_set must not run on a hit


@pytest.mark.asyncio
async def test_performance_cache_hit_preserves_key_order(monkeypatch):
    """Plan criterion: cache hit serves identical key order, not just key set.

    The frontend maps positions, so a reordered dict would silently break the
    panel. Pins the exact insertion order produced by ``_compute``.
    """
    expected_keys = ["window", "response_time", "conversion"]
    cached_payload = {
        "window": "7d",
        "response_time": {"p50_ms": 1, "p95_ms": 2, "trend": []},
        "conversion": {"candidate_chats": 0, "with_phone": 0, "rate_pct": None},
    }
    factory, queries = _make_session_factory(_standard_routes())
    monkeypatch.setattr(perf_mod, "open_background_session", factory)

    async def _hit(_key):
        return cached_payload

    monkeypatch.setattr(perf_mod, "cache_get_json", _hit)

    async def _set(_key, _value, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    out = await performance("7d", _admin=SimpleNamespace())

    assert list(out.keys()) == expected_keys
    assert queries == []


@pytest.mark.asyncio
async def test_performance_cache_failure_falls_through(monkeypatch):
    """If cache_get_json raises, the endpoint still computes and returns correctly.

    ``cache.py``'s helpers swallow exceptions and return None, but the handler
    must remain correct even if a different stub raises — the compute path is
    the source of truth and must run regardless of cache state.
    """
    factory, _ = _make_session_factory(_standard_routes())
    monkeypatch.setattr(perf_mod, "open_background_session", factory)

    async def _raises(_key):
        raise RuntimeError("redis down")

    monkeypatch.setattr(perf_mod, "cache_get_json", _raises)

    async def _noop(_key, _value, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _noop)

    out = await performance("7d", _admin=SimpleNamespace())

    # Compute path ran and produced a well-formed payload.
    assert out["window"] == "7d"
    assert out["response_time"]["p95_ms"] == 2900
    assert out["conversion"]["rate_pct"] == 25.0


@pytest.mark.asyncio
async def test_performance_queries_dispatched_concurrently(monkeypatch):
    """The three DB reads run concurrently via asyncio.gather, not sequentially.

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
            sql = str(stmt)
            if _ROUTE_CONVERSION in sql:
                return _FakeResult(one=SimpleNamespace(candidate_chats=0, with_phone=0))
            if _ROUTE_TREND in sql:
                return _FakeResult(all_rows=[])
            if _ROUTE_PERCENTILES in sql:
                return _FakeResult(one=SimpleNamespace(p50_ms=None, p95_ms=None))
            raise AssertionError(f"unmatched SQL: {sql[:80]}")

    class _CM:
        async def __aenter__(self):
            return _ConcurrencySession()

        async def __aexit__(self, *exc):
            return False

    def factory():
        return _CM()

    monkeypatch.setattr(perf_mod, "open_background_session", factory)

    async def _miss(_key):
        return None

    monkeypatch.setattr(perf_mod, "cache_get_json", _miss)

    async def _set(_k, _v, ttl_seconds):
        return None

    monkeypatch.setattr(perf_mod, "cache_set_json", _set)

    await performance("7d", _admin=SimpleNamespace())

    # gather ran ≥ 2 reads in flight simultaneously — sequential would be 1.
    assert max_inflight >= 2, f"reads were not concurrent (max_inflight={max_inflight})"


def test_performance_route_rejects_retired_window(monkeypatch):
    """``1h`` is no longer a dashboard window; the route rejects it before the handler.

    Also pins the accepted set to exactly the five period buttons the page renders.
    """

    async def _fake_dashboard(window: str) -> dict:
        return {"window": window}

    monkeypatch.setattr("app.api.performance.performance_dashboard", _fake_dashboard)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="admin")

    with TestClient(app) as client:
        assert client.get("/admin/performance", params={"window": "1h"}).status_code == 422
        for window in ("1d", "7d", "1m", "3m", "6m"):
            resp = client.get("/admin/performance", params={"window": window})
            assert resp.status_code == 200, window
            assert resp.json() == {"window": window}


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
