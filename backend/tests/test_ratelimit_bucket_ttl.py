"""The rate-limit bucket's counter and its window are one indivisible step.

``_enforce_bucket`` runs a single Redis script that INCRs the bucket and arms
its TTL when — and only when — the counter is new. Two properties follow, and
both are load-bearing:

- The counter and its TTL cannot be separated. A process death or dropped
  connection between them is no longer expressible, so a bucket can no longer be
  left counting towards its limit with nothing to reset it.
- A rejected request does not re-arm the window. This is the property that
  constrains the design: re-arming the window on every increment looks
  self-healing, but it means a client that keeps hammering a bucket it is
  already locked out of extends its own lockout on every rejected request. The
  limiter would then pin that caller out indefinitely, with no recovery short
  of an operator deleting the key — on the auth path, strictly worse than the
  race the script exists to close.

Note the window value is constant in these tests, so re-arming the TTL is
invisible in the stored TTL alone — it would write the same number back. The
double therefore counts *arming operations*, which is the only way to observe
the regression.

The double models the script as one uninterruptible step, because that is what
Redis guarantees. Any command the limiter adds beyond this script shows up here
as an ``AttributeError`` rather than as a silently unexercised path.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import ratelimit

WINDOW = 90
LIMIT = 3


def _request(xff: str) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"x-forwarded-for": xff}, client=SimpleNamespace(host="10.0.0.1")
    )


class _BucketRedis:
    """Redis double exposing exactly the script surface the limiter uses."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        # ``None`` means "key exists, no expiry set" — a stranded bucket.
        self.ttls: dict[str, int | None] = {}
        self.arms = 0
        self.fail_next_eval = 0
        self.interleavings = 0

    async def _tick(self) -> None:
        """Yield before the script so concurrent callers queue up realistically."""
        self.interleavings += 1
        await asyncio.sleep(0)

    async def eval(self, _script: str, _numkeys: int, key: str, window: int) -> int:
        await self._tick()
        if self.fail_next_eval:
            self.fail_next_eval -= 1
            raise ConnectionError("redis unavailable")
        # No yield between the INCR and the EXPIRE: Redis runs a script to
        # completion, so the two cannot be interrupted apart.
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] == 1:
            self.arms += 1
            self.ttls[key] = window
        return self.counts[key]

    def strand(self, key: str, count: int) -> None:
        """Seed a bucket with a counter but no window, as an older build could leave it."""
        self.counts[key] = count
        self.ttls[key] = None


def _install(monkeypatch, redis: _BucketRedis) -> None:
    """Run the limiter's production branch against ``redis``."""
    monkeypatch.setattr(
        ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production")
    )
    monkeypatch.setattr(ratelimit, "get_redis", lambda: redis)


async def _record(coro) -> str:
    """Classify one enforcement call as allowed or rejected, without unwinding."""
    try:
        await coro
    except HTTPException as exc:
        return str(exc.status_code)
    return "ok"


@pytest.mark.asyncio
async def test_the_first_hit_arms_the_window(monkeypatch):
    redis = _BucketRedis()
    _install(monkeypatch, redis)

    await ratelimit.enforce_rate_limit(
        _request("203.0.113.7"), "login", limit=LIMIT, window=WINDOW
    )

    assert redis.ttls["rl:login:203.0.113.7"] == WINDOW
    assert redis.arms == 1


@pytest.mark.asyncio
async def test_a_rejected_request_does_not_re_arm_the_window(monkeypatch):
    """The regression this design exists to prevent: an unbounded self-lockout.

    A client that keeps hitting a bucket it is already over budget must not
    re-arm the expiry each time. If it did, the lockout would never end on its
    own and only an operator could clear it.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    req = _request("203.0.113.8")

    for _ in range(LIMIT):
        await ratelimit.enforce_rate_limit(req, "login", limit=LIMIT, window=WINDOW)
    assert redis.arms == 1

    for _ in range(25):
        assert (
            await _record(
                ratelimit.enforce_rate_limit(req, "login", limit=LIMIT, window=WINDOW)
            )
            == "429"
        )

    assert redis.arms == 1
    assert redis.ttls["rl:login:203.0.113.8"] == WINDOW


@pytest.mark.asyncio
async def test_a_stranded_bucket_is_not_rearmed_by_further_requests(monkeypatch):
    """A bucket left without a window stays exactly as stranded.

    Re-arming it here would look like recovery, but it would happen on the
    rejected path — precisely the path that must not extend a lockout. The
    stranded state can only be cleared by the window elapsing, so this asserts
    the window stays ``None`` rather than asserting a repair.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    req = _request("203.0.113.9")
    redis.strand("rl:login:203.0.113.9", count=LIMIT + 5)

    for _ in range(10):
        assert (
            await _record(
                ratelimit.enforce_rate_limit(req, "login", limit=LIMIT, window=WINDOW)
            )
            == "429"
        )
        assert redis.ttls["rl:login:203.0.113.9"] is None

    assert redis.arms == 0


@pytest.mark.asyncio
async def test_the_budget_is_still_enforced_under_concurrent_first_hits(monkeypatch):
    """Atomicity must not cost the limiter its budget.

    Many callers racing on a brand-new bucket must produce exactly ``limit``
    admissions, and the window must be armed exactly once no matter how the
    interleaving fell out.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    req = _request("203.0.113.10")

    outcomes = await asyncio.gather(
        *(
            _record(
                ratelimit.enforce_rate_limit(req, "login", limit=LIMIT, window=WINDOW)
            )
            for _ in range(20)
        )
    )

    assert outcomes.count("ok") == LIMIT
    assert outcomes.count("429") == 20 - LIMIT
    assert redis.counts["rl:login:203.0.113.10"] == 20
    assert redis.ttls["rl:login:203.0.113.10"] == WINDOW
    assert redis.arms == 1


@pytest.mark.asyncio
async def test_concurrent_storms_across_many_buckets_arm_each_window_once(monkeypatch):
    """Per-bucket arming must hold when a storm spans many buckets at once."""
    redis = _BucketRedis()
    _install(monkeypatch, redis)

    buckets = [f"203.0.113.{n}" for n in range(20, 32)]
    outcomes = await asyncio.gather(
        *(
            _record(
                ratelimit.enforce_rate_limit(
                    _request(ip), "login", limit=LIMIT, window=WINDOW
                )
            )
            for ip in buckets
            for _ in range(4)
        )
    )

    assert all(redis.ttls[f"rl:login:{ip}"] == WINDOW for ip in buckets)
    assert all(redis.counts[f"rl:login:{ip}"] == 4 for ip in buckets)
    # 4 hits against a limit of 3 admits 3 per bucket, across 12 buckets.
    assert outcomes.count("ok") == 3 * len(buckets)
    # One arming per bucket, not one per request.
    assert redis.arms == len(buckets)


@pytest.mark.asyncio
async def test_an_unavailable_redis_fails_open_on_the_auth_path(monkeypatch):
    """The limiter is best-effort for auth: a Redis outage must not lock users out.

    This is why the script's failure is survivable at all — the counter never
    lands, so no bucket is left half-written.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    redis.fail_next_eval = 1

    outcome = await _record(
        ratelimit.enforce_rate_limit(
            _request("203.0.113.40"), "login", limit=LIMIT, window=WINDOW
        )
    )

    assert outcome == "ok"
    assert redis.counts == {}
    assert redis.arms == 0


@pytest.mark.asyncio
async def test_the_scarce_llm_budget_fails_closed_when_redis_is_unavailable(monkeypatch):
    """The scarce deployment-wide resource is the opposite case: deny, do not admit.

    An unverifiable budget must not hand out capacity, so the same script failure
    that is survivable on the auth path is a 429 here.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    redis.fail_next_eval = 1

    outcome = await _record(
        ratelimit.enforce_rate_limit(
            _request("203.0.113.41"),
            "llm",
            limit=LIMIT,
            window=WINDOW,
            fail_open=False,
        )
    )

    assert outcome == "429"
    assert redis.counts == {}
    assert redis.arms == 0
