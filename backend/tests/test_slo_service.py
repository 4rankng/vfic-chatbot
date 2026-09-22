"""Tests for the latency SLO service (Tech-Lead Directive §1).

Covers:
- _status_for green/amber/red/unknown thresholds (latency + rate)
- _error_or_timeout_rate percentage math + empty-window handling
- _latency_rollups shape (queue_wait combines webhook_to_pickup + preamble;
  cached/full_answer filter by lane)
- compute_slos returns all 7 SLOs with the documented names + units
- record_webhook_ack_ms / _rollup_webhook_ack Redis path (mocked)

The DB-backed rollups use a fake AsyncSession that returns canned rows so we
don't need a live Postgres. The Redis path is mocked at the import boundary.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.services import slo_service


# ─── _status_for ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,target,is_rate,expected",
    [
        # Latency: green ≤ target, amber ≤ 1.5×, red beyond.
        (50.0, 100.0, False, "green"),
        (100.0, 100.0, False, "green"),
        (101.0, 100.0, False, "amber"),
        (150.0, 100.0, False, "amber"),
        (151.0, 100.0, False, "red"),
        (1000.0, 100.0, False, "red"),
        # None → unknown regardless of target.
        (None, 100.0, False, "unknown"),
        # Rate: green ≤ target, amber ≤ 2× (or target+1, whichever larger), red beyond.
        (0.5, 1.0, True, "green"),
        (1.0, 1.0, True, "green"),
        (1.5, 1.0, True, "amber"),
        (2.0, 1.0, True, "amber"),
        (2.5, 1.0, True, "red"),
        # Zero-target rate (duplicate_outbound_rate_pct = 0): any value > 0 is at least amber.
        (0.0, 0.0, True, "green"),
        (0.1, 0.0, True, "amber"),  # 0.1 ≤ max(0*2, 0+1) = 1.0 → amber
        (2.0, 0.0, True, "red"),  # 2.0 > 1.0 → red
    ],
)
def test_status_for_thresholds(value, target, is_rate, expected):
    assert slo_service._status_for(value, target, is_rate=is_rate) == expected


# ─── _error_or_timeout_rate ──────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, **kwargs: Any):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeDB:
    """Minimal AsyncSession double: returns a canned row from execute().

    The real AsyncSession.execute() is awaitable and returns a Result with
    .one_or_none(); this fake mirrors that by being an async method that
    returns an object with .one_or_none().
    """

    def __init__(self, row: Any):
        self._row = row
        self.executed_sql: str | None = None

    async def execute(self, sql, params=None):
        self.executed_sql = str(sql)
        row = self._row

        class _Result:
            def one_or_none(self_inner):
                return row

        return _Result()


async def test_error_or_timeout_rate_computes_percentage():
    db = _FakeDB(_FakeResult(total=200, bad=3))
    rate = await slo_service._error_or_timeout_rate(db, timedelta(hours=24))
    assert rate == pytest.approx(1.5)


async def test_error_or_timeout_rate_zero_bad():
    db = _FakeDB(_FakeResult(total=100, bad=0))
    rate = await slo_service._error_or_timeout_rate(db, timedelta(hours=24))
    assert rate == 0.0


async def test_error_or_timeout_rate_empty_window_returns_none():
    db = _FakeDB(_FakeResult(total=0, bad=0))
    rate = await slo_service._error_or_timeout_rate(db, timedelta(hours=24))
    assert rate is None


async def test_error_or_timeout_rate_no_rows_returns_none():
    db = _FakeDB(None)
    rate = await slo_service._error_or_timeout_rate(db, timedelta(hours=24))
    assert rate is None


# ─── _latency_rollups ────────────────────────────────────────────────────────


async def test_latency_rollups_returns_none_when_no_rows():
    db = _FakeDB(None)
    out = await slo_service._latency_rollups(db, timedelta(hours=24))
    assert out == {
        "queue_wait": {"p50": None, "p95": None},
        "cached": {"p50": None, "p95": None},
        "full_answer": {"p50": None, "p95": None},
    }


async def test_latency_rollups_maps_columns():
    row = _FakeResult(
        qw_p50=120.0,
        qw_p95=180.0,
        cd_p50=200.0,
        cd_p95=450.0,
        fa_p50=2000.0,
        fa_p95=3800.0,
    )
    db = _FakeDB(row)
    out = await slo_service._latency_rollups(db, timedelta(hours=24))
    assert out["queue_wait"] == {"p50": 120.0, "p95": 180.0}
    assert out["cached"] == {"p50": 200.0, "p95": 450.0}
    assert out["full_answer"] == {"p50": 2000.0, "p95": 3800.0}


# ─── compute_slos end-to-end ─────────────────────────────────────────────────


async def test_compute_slos_returns_seven_named_slos(monkeypatch):
    """All 7 directive SLOs present, with correct names + units."""

    # Stub the DB-backed rollups to known values.
    async def fake_latency(db, interval, **_kwargs):
        return {
            "queue_wait": {"p50": 80.0, "p95": 130.0},  # green (<150)
            "cached": {"p50": 250.0, "p95": 480.0},  # green (<500)
            "full_answer": {"p50": 2200.0, "p95": 3900.0},  # green (<4000)
        }

    async def fake_err_rate(db, interval, **_kwargs):
        return 0.5  # 0.5% < 1.0 → green

    async def fake_ack():
        return (40.0, 90.0)  # green (<100)

    monkeypatch.setattr(slo_service, "_latency_rollups", fake_latency)
    monkeypatch.setattr(slo_service, "_error_or_timeout_rate", fake_err_rate)
    monkeypatch.setattr(slo_service, "_rollup_webhook_ack", fake_ack)

    slos = await slo_service.compute_slos(_FakeDB(None), timedelta(hours=24))
    names = [s.name for s in slos]
    assert names == [
        "webhook_ack",
        "queue_wait",
        "cached_or_deterministic",
        "rag_ttfb",
        "full_answer",
        "error_or_timeout_rate",
        "duplicate_outbound_rate",
    ]

    by_name = {s.name: s for s in slos}

    # Latency SLOs measured as ms.
    assert by_name["webhook_ack"].unit == "ms"
    assert by_name["webhook_ack"].status == "green"
    assert by_name["webhook_ack"].actual_p95 == 90.0

    assert by_name["queue_wait"].unit == "ms"
    assert by_name["queue_wait"].status == "green"

    assert by_name["cached_or_deterministic"].unit == "ms"
    assert by_name["cached_or_deterministic"].status == "green"

    # rag_ttfb is unknown until streaming lands.
    assert by_name["rag_ttfb"].status == "unknown"
    assert by_name["rag_ttfb"].actual_p95 is None

    assert by_name["full_answer"].unit == "ms"
    assert by_name["full_answer"].status == "green"

    # Rate SLOs measured as %.
    assert by_name["error_or_timeout_rate"].unit == "%"
    assert by_name["error_or_timeout_rate"].status == "green"
    assert by_name["error_or_timeout_rate"].actual_p95 == 0.5

    # Duplicate rate is stubbed until P0-5 outbox.
    assert by_name["duplicate_outbound_rate"].status == "unknown"
    assert by_name["duplicate_outbound_rate"].actual_p95 is None


async def test_compute_slos_red_status_when_p95_exceeds_target(monkeypatch):
    """full_answer p95 > 1.5× target → red."""

    async def fake_latency(db, interval, **_kwargs):
        return {
            "queue_wait": {"p50": 80.0, "p95": 130.0},
            "cached": {"p50": 250.0, "p95": 480.0},
            "full_answer": {"p50": 5000.0, "p95": 7_000.0},  # > 1.5×4000 = 6000 → red
        }

    async def fake_err_rate(db, interval, **_kwargs):
        return 0.5

    async def fake_ack():
        return (40.0, 90.0)

    monkeypatch.setattr(slo_service, "_latency_rollups", fake_latency)
    monkeypatch.setattr(slo_service, "_error_or_timeout_rate", fake_err_rate)
    monkeypatch.setattr(slo_service, "_rollup_webhook_ack", fake_ack)

    slos = await slo_service.compute_slos(_FakeDB(None), timedelta(hours=24))
    by_name = {s.name: s for s in slos}
    assert by_name["full_answer"].status == "red"


async def test_compute_slos_amber_when_between_target_and_1_5x(monkeypatch):
    async def fake_latency(db, interval, **_kwargs):
        return {
            "queue_wait": {"p50": 100.0, "p95": 200.0},  # 150 < 200 ≤ 225 → amber
            "cached": {"p50": 250.0, "p95": 480.0},
            "full_answer": {"p50": 2200.0, "p95": 3900.0},
        }

    async def fake_err_rate(db, interval, **_kwargs):
        return 0.5

    async def fake_ack():
        return (40.0, 90.0)

    monkeypatch.setattr(slo_service, "_latency_rollups", fake_latency)
    monkeypatch.setattr(slo_service, "_error_or_timeout_rate", fake_err_rate)
    monkeypatch.setattr(slo_service, "_rollup_webhook_ack", fake_ack)

    slos = await slo_service.compute_slos(_FakeDB(None), timedelta(hours=24))
    by_name = {s.name: s for s in slos}
    assert by_name["queue_wait"].status == "amber"


async def test_compute_slos_error_rate_red_when_over_target(monkeypatch):
    async def fake_latency(db, interval, **_kwargs):
        return {
            "queue_wait": {"p50": 80.0, "p95": 130.0},
            "cached": {"p50": 250.0, "p95": 480.0},
            "full_answer": {"p50": 2200.0, "p95": 3900.0},
        }

    async def fake_err_rate(db, interval, **_kwargs):
        return 5.0  # > 2×1.0 → red

    async def fake_ack():
        return (40.0, 90.0)

    monkeypatch.setattr(slo_service, "_latency_rollups", fake_latency)
    monkeypatch.setattr(slo_service, "_error_or_timeout_rate", fake_err_rate)
    monkeypatch.setattr(slo_service, "_rollup_webhook_ack", fake_ack)

    slos = await slo_service.compute_slos(_FakeDB(None), timedelta(hours=24))
    by_name = {s.name: s for s in slos}
    assert by_name["error_or_timeout_rate"].status == "red"


# ─── Webhook-ack Redis sliding window ────────────────────────────────────────


class _FakeRedis:
    """Records incrbyfloat / incr / zadd / zrange calls for ack SLO tests."""

    def __init__(self):
        self.sum = 0.0
        self.count = 0
        self.samples: list[tuple[str, float]] = []  # (member, score)
        self.expires: dict[str, int] = {}

    async def incrbyfloat(self, key, val):
        if key == slo_service._ACK_SUM_KEY:
            self.sum += float(val)

    async def incr(self, key):
        if key == slo_service._ACK_COUNT_KEY:
            self.count += 1

    async def zadd(self, key, mapping):
        for member, score in mapping.items():
            self.samples.append((member, float(score)))

    async def zcard(self, key):
        return len(self.samples)

    async def zremrangebyrank(self, key, start, end):
        pass  # trim not exercised in tests

    async def expire(self, key, ttl):
        self.expires[key] = int(ttl)

    async def get(self, key):
        if key == slo_service._ACK_SUM_KEY:
            return str(self.sum) if self.sum else None
        if key == slo_service._ACK_COUNT_KEY:
            return str(self.count) if self.count else None
        return None

    async def zrange(self, key, start, end, withscores=False):
        sorted_samples = sorted(self.samples, key=lambda x: x[1])
        # Clamp indices like Redis (negative = from end).
        n = len(sorted_samples)
        if n == 0:
            return []
        idx = start if start >= 0 else n + start
        idx = max(0, min(idx, n - 1))
        if withscores:
            return [sorted_samples[idx]]
        return [sorted_samples[idx][0]]


async def test_record_webhook_ack_ms_writes_to_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _async_return(fake))

    await slo_service.record_webhook_ack_ms(75.0)

    assert fake.sum == 75.0
    assert fake.count == 1
    assert len(fake.samples) == 1
    assert fake.samples[0][1] == 75.0
    # TTLs refreshed on all three keys.
    assert fake.expires[slo_service._ACK_SUM_KEY] == slo_service._ACK_BUCKET_TTL_SECONDS
    assert fake.expires[slo_service._ACK_COUNT_KEY] == slo_service._ACK_BUCKET_TTL_SECONDS
    assert fake.expires[slo_service._ACK_SAMPLES_KEY] == slo_service._ACK_BUCKET_TTL_SECONDS


async def test_record_webhook_ack_ms_swallows_redis_errors(monkeypatch):
    """Redis failure must NOT propagate — instrumentation is best-effort."""

    async def raising():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis", raising)
    # Should not raise.
    await slo_service.record_webhook_ack_ms(75.0)


async def test_rollup_webhook_ack_returns_none_when_empty(monkeypatch):
    fake = _FakeRedis()  # no samples
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _async_return(fake))
    p50, p95 = await slo_service._rollup_webhook_ack()
    assert p50 is None
    assert p95 is None


async def test_rollup_webhook_ack_computes_p50_and_p95(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _async_return(fake))

    # 19 samples of 10ms + 1 sample of 1000ms = 20 total.
    # p95: idx = int(20 * 0.95) = 19 → sorted_samples[19] = 1000 (the outlier).
    # p50 = mean = (19*10 + 1000)/20 = 59.5ms.
    for _ in range(19):
        await slo_service.record_webhook_ack_ms(10.0)
    await slo_service.record_webhook_ack_ms(1000.0)

    p50, p95 = await slo_service._rollup_webhook_ack()
    assert p50 == pytest.approx((19 * 10 + 1000) / 20, rel=0.01)
    assert p95 == 1000.0


# ─── helpers ─────────────────────────────────────────────────────────────────


class _Awaitable:
    """Wraps a value so awaiting it returns the value (mimics async get_redis())."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _coro():
            return self._value

        return _coro().__await__()


def _async_return(value):
    return _Awaitable(value)


async def test_synthetic_filter_only_applies_when_requested(monkeypatch):
    """The dashboard keeps seed demo data; only the release gate excludes it."""
    captured: list[str] = []

    async def fake_latency(db, interval, **kwargs):
        captured.append("latency")
        return {"queue_wait": {"p50": None, "p95": None}, "cached": {"p50": None, "p95": None}, "full_answer": {"p50": None, "p95": None}}

    async def fake_err_rate(db, interval, **kwargs):
        captured.append("err")
        return None

    monkeypatch.setattr(slo_service, "_latency_rollups", fake_latency)
    monkeypatch.setattr(slo_service, "_error_or_timeout_rate", fake_err_rate)
    monkeypatch.setattr(slo_service, "_rollup_webhook_ack", lambda: _noop_ack())

    default = slo_service._SYNTHETIC_FILTER
    assert "synthetic" in default

    class _CaptureSession:
        def __init__(self) -> None:
            self.sql: list[str] = []

        async def execute(self, statement, params=None):
            self.sql.append(str(statement))

            class _R:
                def scalar_one(self):
                    return 5

                def one_or_none(self):
                    return None

            return _R()

    db = _CaptureSession()
    await slo_service.count_measured_runs(db, timedelta(hours=24))
    assert default not in db.sql[0]

    db2 = _CaptureSession()
    await slo_service.count_measured_runs(db2, timedelta(hours=24), exclude_synthetic=True)
    assert default in db2.sql[0]


async def _noop_ack():
    return None, None
