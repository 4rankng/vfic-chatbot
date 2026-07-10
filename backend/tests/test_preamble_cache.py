"""Tests for the shared-preamble cache (integration settings + system prompt).

Covers: cache hit/miss, version-bump invalidation, Redis-down safety, and the
invariant that ``resolve_zalo`` is never cached. All I/O (Redis) is mocked —
no live process required.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.core.preamble_cache import (
    NS_INTEGRATION_MINIMAX,
    NS_INTEGRATION_OPENROUTER,
    NS_PREAMBLE,
    cached_minimax_config,
    cached_openrouter_config,
    cached_system_prompt,
    cached_value,
)


# ── Test doubles ─────────────────────────────────────────────────────────


class _FakeRedis:
    """In-memory async Redis double supporting get/set/incr on string values."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> str:
        self._store[key] = value
        return "OK"

    async def incr(self, key: str) -> int:
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])


class _ExplodingRedis:
    """Redis double that always raises, simulating a Redis outage."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, *, ex: int | None = None) -> str:
        raise RuntimeError("redis down")

    async def incr(self, key: str) -> int:
        raise RuntimeError("redis down")


# ── cached_value (the generic primitive) ──────────────────────────────────


@pytest.mark.asyncio
async def test_cached_value_hits_db_on_miss_then_caches(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

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
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    # cache_version returns "1" for an absent key, and the first incr() also
    # yields "1" — so a single bump from a fresh state is a no-op. In production
    # the write path bumps during initial setup (before any chatbot read), which
    # establishes the baseline. Mirror that here.
    from app.core.cache import bump_cache_version

    await bump_cache_version("test_ns")  # baseline → version "1"

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return f"v{calls['n']}"

    await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )
    # Bump again — the next read must miss and re-load.
    await bump_cache_version("test_ns")  # → version "2"
    out = await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )

    assert out == "v2"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cached_value_redis_down_falls_through_to_loader(monkeypatch):
    redis = _ExplodingRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    async def loader():
        return "live-value"

    out = await cached_value(
        key_prefix="test:k", namespace="test_ns", ttl_seconds=60, loader=loader
    )
    assert out == "live-value"  # no exception escapes


# ── typed helpers (minimax / openrouter / system prompt) ─────────────────


@pytest.mark.asyncio
async def test_cached_minimax_config_caches_dict(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"api_key": "sk-1", "enabled": True}

    assert await cached_minimax_config(loader) == {"api_key": "sk-1", "enabled": True}
    assert await cached_minimax_config(loader) == {"api_key": "sk-1", "enabled": True}
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cached_openrouter_config_caches_dict(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return {"api_key": "sk-or-1"}

    await cached_openrouter_config(loader)
    await cached_openrouter_config(loader)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cached_system_prompt_round_trips_string(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.cache.get_redis", lambda: redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "PERSONA+INDEX"

    assert await cached_system_prompt(loader) == "PERSONA+INDEX"
    assert await cached_system_prompt(loader) == "PERSONA+INDEX"
    assert calls["n"] == 1


# ── resolve_zalo is never cached (the token-rotation invariant) ───────────


@pytest.mark.asyncio
async def test_resolve_zalo_is_not_cached():
    """resolve_zalo must always read from the DB; caching would break OA token refresh."""
    from app.services.integration_settings import (
        IntegrationSettingsService,
        ZALO_OA_REFRESH_TOKEN,
    )

    class _SettingsZalo:
        integration_settings_encryption_key = "test-integration-key"
        jwt_secret = "x"
        zalo_bot_token = ""
        zalo_bot_webhook_secret = ""
        zalo_oa_app_id = ""
        zalo_oa_secret_key = ""
        zalo_oa_access_token = ""
        zalo_oa_refresh_token = ""

    class _Row:
        def __init__(self, key, encrypted_value):
            self.key = key
            self.encrypted_value = encrypted_value
            self.is_secret = True
            self.updated_by = None

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Db:
        def __init__(self, rows):
            self._rows = rows
            self.scalars_calls = 0

        async def scalars(self, _q):
            self.scalars_calls += 1
            return _Result(self._rows)

    svc = IntegrationSettingsService(_Db([]), settings=_SettingsZalo())
    encrypted = svc.cipher.encrypt("rt-secret")
    db = _Db([_Row(ZALO_OA_REFRESH_TOKEN, encrypted)])
    svc = IntegrationSettingsService(db, settings=_SettingsZalo())

    await svc.resolve_zalo()
    await svc.resolve_zalo()

    # Both calls hit the DB — no caching layer intercepts resolve_zalo.
    assert db.scalars_calls == 2
