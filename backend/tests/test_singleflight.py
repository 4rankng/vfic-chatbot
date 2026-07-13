"""Tests for cross-process single-flight coalescing (Tech-Lead Directive §6).

The primitive is Redis-backed, so these tests use a fake Redis that implements
the subset of methods singleflight uses: ``set(nx=True, ex=)``, ``get``,
``delete``, ``publish``, ``pubsub``. The fake simulates the leader-follower
handshake deterministically without needing a real Redis or cross-process
coordination.

Covers:
- acquire: first caller wins, second caller is None
- release: owner releases; non-owner does not release
- run_as_leader: success publishes result + releases; error publishes error + re-raises
- await_result: follower receives leader's result
- await_result: follower receives leader's error as SingleFlightError
- await_result: follower times out → asyncio.TimeoutError
- await_result: cache_read short-circuits (leader already wrote the cache)
- Redis unavailable: acquire returns None; await_result raises TimeoutError
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import singleflight


# ─── Fake Redis (in-process, deterministic) ──────────────────────────────────


class _FakePubSub:
    """Minimal pubsub double: ``subscribe`` + ``listen`` yields queued messages."""

    def __init__(self, channel: str, messages: list[dict]):
        self._channel = channel
        self._messages = list(messages)
        self._subscribed = False
        self._closed = False

    async def subscribe(self, channel: str):
        assert channel == self._channel
        self._subscribed = True

    async def unsubscribe(self, channel: str):
        pass

    async def aclose(self):
        self._closed = True

    async def listen(self):
        for msg in self._messages:
            yield msg


class _FakeRedis:
    """In-memory Redis double for singleflight tests.

    Backs ``set(nx, ex)``, ``get``, ``delete``, ``publish``, ``pubsub``. The
    pubsub messages list is shared across all _FakeRedis instances created from
    the same factory so a leader's publish reaches a follower's listen().
    """

    # Class-level shared state so leader and follower (separate instances) see
    # the same keys and the same pubsub queue. Reset per-test via _reset().
    _store: dict[str, str] = {}
    _channels: dict[str, list[dict]] = {}

    @classmethod
    def _reset(cls):
        cls._store.clear()
        cls._channels.clear()

    def __init__(self):
        # Use the shared class-level dicts.
        pass

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx:
            if key in self._store:
                return None
            self._store[key] = value
            return "OK"
        self._store[key] = value
        return "OK"

    async def get(self, key: str):
        return self._store.get(key)

    async def delete(self, key: str):
        return self._store.pop(key, None) is not None

    async def publish(self, channel: str, message: str):
        self._channels.setdefault(channel, []).append(
            {"type": "message", "channel": channel, "data": message.encode("utf-8")}
        )
        return 1

    def pubsub(self):
        # Return a pubsub that will yield whatever has been published to the
        # result channel so far. Tests pre-populate _channels before awaiting.
        return _QueuedPubSub(self._channels)


class _QueuedPubSub(_FakePubSub):
    """A pubsub whose listen() drains the shared channel queue at call time."""

    def __init__(self, channels: dict[str, list[dict]]):
        self._channels = channels
        self._channel: str | None = None

    async def subscribe(self, channel: str):
        self._channel = channel

    async def unsubscribe(self, channel: str):
        pass

    async def aclose(self):
        pass

    async def listen(self):
        if self._channel is None:
            return
        # Drain whatever is currently queued. (Deterministic; tests pre-publish.)
        queue = self._channels.get(self._channel, [])
        for msg in queue:
            yield msg


@pytest.fixture(autouse=True)
def _reset_fake_redis(monkeypatch):
    """Fresh fake Redis per test + point singleflight at it."""
    _FakeRedis._reset()

    # Patch the lazy accessor so singleflight._get_redis returns our fake.
    async def _fake_get_redis():
        return _FakeRedis()

    monkeypatch.setattr(singleflight, "_get_redis", _fake_get_redis)
    yield
    _FakeRedis._reset()


# ─── acquire / release ───────────────────────────────────────────────────────


async def test_acquire_first_caller_wins():
    leader = await singleflight.acquire("k1")
    assert leader is not None
    follower = await singleflight.acquire("k1")
    assert follower is None


async def test_acquire_different_keys_both_win():
    a = await singleflight.acquire("k1")
    b = await singleflight.acquire("k2")
    assert a is not None
    assert b is not None
    assert a != b


async def test_release_owner_clears_marker():
    leader_id = await singleflight.acquire("k1")
    assert leader_id is not None
    await singleflight.release("k1", leader_id)
    # After release, a new caller can acquire.
    next_leader = await singleflight.acquire("k1")
    assert next_leader is not None
    assert next_leader != leader_id


async def test_release_non_owner_does_not_clear():
    """A straggler leader must not release a new leader's marker."""
    first = await singleflight.acquire("k1")
    assert first is not None
    # Simulate TTL expiry + new leader takeover.
    _FakeRedis._store[singleflight._INFLIGHT_KEY.format(key="k1")] = "new-leader"
    # Old leader tries to release — should NOT clear the new leader's marker.
    await singleflight.release("k1", first)
    assert _FakeRedis._store[singleflight._INFLIGHT_KEY.format(key="k1")] == "new-leader"


# ─── run_as_leader ───────────────────────────────────────────────────────────


async def test_run_as_leader_success_publishes_and_releases():
    leader_id = await singleflight.acquire("k1")
    assert leader_id is not None

    async def compute():
        return "the answer"

    result = await singleflight.run_as_leader("k1", leader_id, compute)
    assert result == "the answer"
    # Marker released.
    assert singleflight._INFLIGHT_KEY.format(key="k1") not in _FakeRedis._store
    # Result published to the channel.
    channel = singleflight._RESULT_CHANNEL.format(key="k1")
    assert channel in _FakeRedis._channels
    assert len(_FakeRedis._channels[channel]) == 1


async def test_run_as_leader_error_publishes_error_and_releases():
    leader_id = await singleflight.acquire("k1")
    assert leader_id is not None

    async def compute():
        raise RuntimeError("model timeout")

    with pytest.raises(RuntimeError, match="model timeout"):
        await singleflight.run_as_leader("k1", leader_id, compute)
    # Marker still released despite the error.
    assert singleflight._INFLIGHT_KEY.format(key="k1") not in _FakeRedis._store
    # Error published to the channel.
    channel = singleflight._RESULT_CHANNEL.format(key="k1")
    assert channel in _FakeRedis._channels
    # The payload encodes the error.
    import json

    payload = json.loads(_FakeRedis._channels[channel][0]["data"])
    assert payload["ok"] is False
    assert payload["error_type"] == "RuntimeError"


# ─── await_result (follower path) ────────────────────────────────────────────


async def test_await_result_receives_leader_result():
    """Leader publishes before follower subscribes → follower finds via cache OR pubsub."""
    # Simulate: leader has already published the result to the channel.
    import json

    channel = singleflight._RESULT_CHANNEL.format(key="k1")
    _FakeRedis._channels[channel] = [
        {
            "type": "message",
            "channel": channel,
            "data": json.dumps({"ok": True, "result": "answer"}).encode(),
        }
    ]
    result = await singleflight.await_result("k1", timeout=1.0)
    assert result == "answer"


async def test_await_result_receives_leader_error_as_singleflight_error():
    import json

    channel = singleflight._RESULT_CHANNEL.format(key="k1")
    _FakeRedis._channels[channel] = [
        {
            "type": "message",
            "channel": channel,
            "data": json.dumps(
                {"ok": False, "error_type": "RuntimeError", "message": "boom"}
            ).encode(),
        }
    ]
    with pytest.raises(singleflight.SingleFlightError, match="boom"):
        await singleflight.await_result("k1", timeout=1.0)


async def test_await_result_cache_read_short_circuits():
    """If cache_read returns a value, follower uses it without subscribing."""
    cached_value = "cached-answer"

    async def cache_read():
        return cached_value

    result = await singleflight.await_result("k1", timeout=0.5, cache_read=cache_read)
    assert result == cached_value


async def test_await_result_timeout_raises():
    """No leader message and no cache hit → asyncio.TimeoutError."""
    with pytest.raises(asyncio.TimeoutError):
        await singleflight.await_result("k1", timeout=0.3)


async def test_await_result_timeout_falls_back_to_cache():
    """After pub/sub timeout, a final cache check can still recover the result."""
    # No message queued → pub/sub will time out. But cache_read returns a value
    # on the second call (simulating leader finishing during the wait).
    call_count = [0]

    async def cache_read():
        call_count[0] += 1
        if call_count[0] >= 2:
            return "late-answer"
        return None

    # The timeout is 0.3s; the follower should fall back to the second cache_read.
    result = await singleflight.await_result("k1", timeout=0.3, cache_read=cache_read)
    assert result == "late-answer"


# ─── Redis unavailable ───────────────────────────────────────────────────────


async def test_acquire_returns_none_when_redis_unavailable(monkeypatch):
    async def _no_redis():
        return None

    monkeypatch.setattr(singleflight, "_get_redis", _no_redis)
    assert await singleflight.acquire("k1") is None


async def test_await_result_raises_timeout_when_redis_unavailable(monkeypatch):
    async def _no_redis():
        return None

    monkeypatch.setattr(singleflight, "_get_redis", _no_redis)
    with pytest.raises(asyncio.TimeoutError):
        await singleflight.await_result("k1", timeout=0.1)
