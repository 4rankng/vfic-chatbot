"""Tests for the shared-preamble cache helpers.

Covers: process-local secret-cache hit/miss, version invalidation, Redis-outage
bypass, TTL expiry, bounded growth, and unchanged Redis-backed system-prompt
behavior. All I/O (Redis) is mocked — no live process required.
"""

from __future__ import annotations

import pytest

from app.core import preamble_cache
from app.core.preamble_cache import (
    cached_minimax_config,
    cached_openrouter_config,
    cached_system_prompt,
    cached_value,
)


@pytest.fixture(autouse=True)
def _reset_local_secret_cache():
    preamble_cache._reset_local_secret_cache()
    yield
    preamble_cache._reset_local_secret_cache()


# ── Test doubles ─────────────────────────────────────────────────────────


class _FakeRedis:
    """In-memory async Redis double supporting get/set/incr on string values."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None, bool]] = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self._store:
            return False
        self._store[key] = value
        return "OK"

    async def incr(self, key: str) -> int:
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


class _ExplodingRedis:
    """Redis double that always raises, simulating a Redis outage."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis down")

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> str:
        raise RuntimeError("redis down")

    async def incr(self, key: str) -> int:
        raise RuntimeError("redis down")


# ── cached_value (the generic primitive) ──────────────────────────────────


@pytest.mark.asyncio
async def test_cached_value_hits_db_on_miss_then_caches(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"v": 1}

    out1 = await cached_value(
        key_prefix="test:k",
        namespace="test_ns",
        ttl_seconds=60,
        loader=loader,
    )
    out2 = await cached_value(
        key_prefix="test:k",
        namespace="test_ns",
        ttl_seconds=60,
        loader=loader,
    )

    assert out1 == {"v": 1}
    assert out2 == {"v": 1}
    assert calls["n"] == 1  # loader invoked only on the miss


@pytest.mark.asyncio
async def test_cached_value_version_bump_invalidates(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    from app.core.cache import bump_cache_version

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return f"v{calls['n']}"

    await cached_value(key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader)
    await bump_cache_version("test_ns")  # logical default 1 → version 2
    out = await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )

    assert out == "v2"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cached_value_redis_version_outage_bypasses_local_cache(monkeypatch):
    healthy_redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: healthy_redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return f"live-value-{calls['n']}"

    first = await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )
    assert first == "live-value-1"

    failing_redis = _ExplodingRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: failing_redis)

    second = await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )

    assert second == "live-value-2"
    assert calls["n"] == 2


# ── typed helpers (minimax / openrouter / system prompt) ─────────────────


@pytest.mark.asyncio
async def test_cached_minimax_config_caches_dict(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"api_key": "sk-1", "enabled": True}

    assert await cached_minimax_config(loader) == {"api_key": "sk-1", "enabled": True}
    assert await cached_minimax_config(loader) == {"api_key": "sk-1", "enabled": True}
    assert calls["n"] == 1
    assert redis.set_calls == []
    assert all("sk-1" not in value for value in redis._store.values())


@pytest.mark.asyncio
async def test_cached_openrouter_config_caches_dict(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"api_key": "sk-or-1"}

    await cached_openrouter_config(loader)
    await cached_openrouter_config(loader)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cached_value_expires_using_monotonic_ttl(monkeypatch):
    redis = _FakeRedis()
    clock = {"now": 100.0}
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)
    monkeypatch.setattr(preamble_cache, "_MONOTONIC", lambda: clock["now"])

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"value": calls["n"]}

    assert await cached_value(
        key_prefix="ttl:k",
        namespace="ttl_ns",
        ttl_seconds=5,
        loader=loader,
    ) == {"value": 1}
    clock["now"] = 104.9
    assert await cached_value(
        key_prefix="ttl:k",
        namespace="ttl_ns",
        ttl_seconds=5,
        loader=loader,
    ) == {"value": 1}
    clock["now"] = 105.1
    assert await cached_value(
        key_prefix="ttl:k",
        namespace="ttl_ns",
        ttl_seconds=5,
        loader=loader,
    ) == {"value": 2}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cached_value_enforces_small_process_local_bound(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)
    monkeypatch.setattr(preamble_cache, "_LOCAL_SECRET_CACHE_MAX_ENTRIES", 2)

    calls = {"ns1": 0, "ns2": 0, "ns3": 0}

    def _loader(namespace: str):
        async def _load():
            calls[namespace] += 1
            return namespace

        return _load

    await cached_value(
        key_prefix="bound:k1",
        namespace="ns1",
        ttl_seconds=60,
        loader=_loader("ns1"),
    )
    await cached_value(
        key_prefix="bound:k2",
        namespace="ns2",
        ttl_seconds=60,
        loader=_loader("ns2"),
    )
    await cached_value(
        key_prefix="bound:k3",
        namespace="ns3",
        ttl_seconds=60,
        loader=_loader("ns3"),
    )

    assert len(preamble_cache._LOCAL_SECRET_CACHE) == 2

    await cached_value(
        key_prefix="bound:k1",
        namespace="ns1",
        ttl_seconds=60,
        loader=_loader("ns1"),
    )
    assert calls["ns1"] == 2
    assert calls["ns2"] == 1
    assert calls["ns3"] == 1


@pytest.mark.asyncio
async def test_cached_system_prompt_round_trips_string(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "PERSONA+INDEX"

    # First call: cache miss → loader runs, returns (value, False).
    value, hit = await cached_system_prompt(loader)
    assert value == "PERSONA+INDEX"
    assert hit is False
    # Second call: cache hit → loader does NOT run, returns (value, True).
    value, hit = await cached_system_prompt(loader)
    assert value == "PERSONA+INDEX"
    assert hit is True
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cached_system_prompt_is_isolated_by_provider_suffix(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return f"PROMPT-{calls['n']}"

    first, first_hit = await cached_system_prompt(loader, key_suffix="zalo_bot")
    second, second_hit = await cached_system_prompt(loader, key_suffix="zalo_oa")
    again, again_hit = await cached_system_prompt(loader, key_suffix="zalo_bot")

    assert (first, first_hit) == ("PROMPT-1", False)
    assert (second, second_hit) == ("PROMPT-2", False)
    assert (again, again_hit) == ("PROMPT-1", True)
    assert calls["n"] == 2
