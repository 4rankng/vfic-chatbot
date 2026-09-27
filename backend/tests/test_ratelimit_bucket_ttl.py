"""The rate-limit bucket can never be left counting without a window TTL.

``_enforce_bucket`` issues its counter and its expiry as two separate Redis
commands, so the interval between them is a real window in which a dead
process or a dropped connection leaves ``rl:<prefix>:<bucket>`` counting
towards its limit with nothing to reset it. Every later request then pushes the
count further over the limit and the caller is 429'd until an operator deletes
the key by hand — on the auth path the limiter exists to keep available.

These tests drive the production branch against a Redis double that keeps real
TTL state (and a real expiry clock is not needed: the assertion is that a TTL
is *armed*, and by how much). Faults are injected exactly where production
faults land — the EXPIRE that follows the first INCR — and the invariant is
checked after the storm has settled, sequentially and under concurrency.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import ratelimit

WINDOW = 90


def _request(xff: str) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"x-forwarded-for": xff}, client=SimpleNamespace(host="10.0.0.1")
    )


class _BucketRedis:
    """Redis double with real TTL state for the commands the limiter issues.

    Implements only ``incr`` and ``expire`` — the whole surface ``_enforce_bucket``
    uses — so a command added to the limiter without updating this double shows up
    here as an ``AttributeError`` rather than as a silently unexercised path.

    ``fail_expires`` makes the next N EXPIRE calls raise the way a dropped
    connection does: the INCR has already landed, the expiry never does. Every
    command yields first so concurrent callers genuinely interleave instead of
    each running to completion.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        # ``None`` means "key exists, no expiry set" — the poisoned state.
        self.ttls: dict[str, int | None] = {}
        self.fail_expires = 0
        self.interleavings = 0

    async def _tick(self) -> None:
        self.interleavings += 1
        await asyncio.sleep(0)

    async def incr(self, key: str) -> int:
        await self._tick()
        self.counts[key] = self.counts.get(key, 0) + 1
        self.ttls.setdefault(key, None)
        return self.counts[key]

    async def expire(self, key: str, window: int) -> None:
        await self._tick()
        if self.fail_expires:
            self.fail_expires -= 1
            raise ConnectionError("connection dropped before EXPIRE landed")
        self.ttls[key] = window

    def poison(self, key: str, count: int) -> None:
        """Seed a bucket the way a crash between INCR and EXPIRE leaves it."""
        self.counts[key] = count
        self.ttls[key] = None


def _install(monkeypatch, redis: _BucketRedis) -> None:
    """Run the limiter's production branch against ``redis``."""
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    monkeypatch.setattr(ratelimit, "get_redis", lambda: redis)


async def _record(coro) -> str:
    """Classify one enforcement call as allowed or rejected, without unwinding."""
    try:
        await coro
    except HTTPException as exc:
        return str(exc.status_code)
    return "ok"


@pytest.mark.asyncio
async def test_the_first_increment_always_arms_the_window(monkeypatch):
    redis = _BucketRedis()
    _install(monkeypatch, redis)

    await ratelimit.enforce_rate_limit(_request("203.0.113.7"), "login", limit=5, window=WINDOW)

    assert redis.ttls["rl:login:203.0.113.7"] == WINDOW


@pytest.mark.asyncio
async def test_a_bucket_that_lost_its_ttl_is_rearmed_instead_of_staying_429_forever(monkeypatch):
    """The regression: a counter stranded without a TTL must not self-perpetuate.

    Seeding the bucket over its limit with no expiry is exactly what a process
    death between the INCR and the EXPIRE leaves behind. The 429 below is correct
    — the count really is over budget — but the expiry it re-arms is what lets the
    caller back out of that state on their own instead of needing an operator.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    redis.poison("rl:login:203.0.113.9", count=9)

    with pytest.raises(HTTPException) as exc:
        await ratelimit.enforce_rate_limit(_request("203.0.113.9"), "login", limit=5, window=WINDOW)
    assert exc.value.status_code == 429

    assert redis.ttls["rl:login:203.0.113.9"] == WINDOW


@pytest.mark.asyncio
async def test_a_dropped_connection_between_incr_and_expire_is_healed_by_the_next_request(
    monkeypatch,
):
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    # The first request's INCR lands; its EXPIRE dies with the connection. The
    # limiter fails open (auth must stay available), leaving a TTL-less counter.
    redis.fail_expires = 1

    await ratelimit.enforce_rate_limit(_request("198.51.100.4"), "login", limit=5, window=WINDOW)

    assert redis.counts["rl:login:198.51.100.4"] == 1
    assert redis.ttls["rl:login:198.51.100.4"] is None

    # The next request must re-establish the window rather than add to a bucket
    # that could never reset.
    await ratelimit.enforce_rate_limit(_request("198.51.100.4"), "login", limit=5, window=WINDOW)

    assert redis.ttls["rl:login:198.51.100.4"] == WINDOW


@pytest.mark.asyncio
async def test_a_dropped_expiry_on_a_fail_closed_bucket_is_healed_too(monkeypatch):
    """The LLM bucket fails closed, so the poisoned counter is denied and grows.

    It must still be re-armed, or that one Redis blip costs the user their LLM
    budget for the lifetime of the deployment.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    redis.fail_expires = 1
    key = "rl:web-chat-turn:user-1"

    with pytest.raises(HTTPException) as exc:
        await ratelimit.enforce_rate_limit_key(
            "web-chat-turn", "user-1", limit=1, window=WINDOW, fail_open=False
        )
    assert exc.value.status_code == 429
    assert redis.ttls[key] is None

    with pytest.raises(HTTPException):
        await ratelimit.enforce_rate_limit_key(
            "web-chat-turn", "user-1", limit=1, window=WINDOW, fail_open=False
        )

    assert redis.ttls[key] == WINDOW


@pytest.mark.asyncio
async def test_concurrent_first_hits_leave_the_bucket_armed_and_counted_exactly(monkeypatch):
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    request = _request("203.0.113.20")
    key = "rl:login:203.0.113.20"

    await asyncio.gather(
        *(
            ratelimit.enforce_rate_limit(request, "login", limit=1000, window=WINDOW)
            for _ in range(50)
        )
    )

    assert redis.counts[key] == 50
    assert redis.ttls[key] == WINDOW
    # The commands really did interleave; a fake that ran each caller to
    # completion could not have caught an INCR racing an EXPIRE.
    assert redis.interleavings > 50


@pytest.mark.asyncio
async def test_a_concurrent_storm_that_loses_expiries_still_ends_with_every_bucket_armed(
    monkeypatch,
):
    """Concurrency plus a flaky connection: the invariant has to survive both.

    Distinct clients, distinct buckets, EXPIRE failing for some of them — after
    the storm every counter that exists must carry a window, otherwise whichever
    request comes next inherits a bucket that can never reset.
    """
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    clients = [f"203.0.113.{n}" for n in range(1, 13)]
    # Every third EXPIRE dies mid-storm, so the buckets end up in a mix of
    # armed, never-armed, and never-re-armed states.
    redis.fail_expires = 6

    async def hit(ip: str) -> None:
        try:
            await ratelimit.enforce_rate_limit(_request(ip), "login", limit=1000, window=WINDOW)
        except HTTPException as exc:  # pragma: no cover - the budget is never reached
            raise AssertionError(f"a 1000-request budget cannot be exhausted: {exc}")

    # Two rounds: the first leaves some buckets armed by luck, the second must
    # re-arm every one of them.
    await asyncio.gather(*(hit(ip) for ip in clients))
    await asyncio.gather(*(hit(ip) for ip in clients))

    assert redis.fail_expires == 0
    assert {ip: redis.ttls[f"rl:login:{ip}"] for ip in clients} == {ip: WINDOW for ip in clients}
    assert all(redis.counts[f"rl:login:{ip}"] == 2 for ip in clients)


@pytest.mark.asyncio
async def test_concurrent_hits_still_spend_the_shared_budget(monkeypatch):
    """Arming the TTL must not let requests past the limit — including racing ones."""
    redis = _BucketRedis()
    _install(monkeypatch, redis)
    request = _request("198.51.100.30")
    key = "rl:login:198.51.100.30"

    outcomes = await asyncio.gather(
        *(
            _record(ratelimit.enforce_rate_limit(request, "login", limit=4, window=WINDOW))
            for _ in range(20)
        )
    )

    assert redis.counts[key] == 20
    assert outcomes.count("ok") == 4
    assert outcomes.count("429") == 16
