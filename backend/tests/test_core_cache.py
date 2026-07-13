"""Tests for app/core/cache.py helpers.

Covers ``bump_kb_caches`` — the helper that invalidates both KB-backed caches
(exact-hash RAG + semantic) together on any KB content mutation. All I/O
(Redis) is mocked — no live process required, matching the preamble-cache test
style.
"""

from __future__ import annotations

import pytest

from app.core import cache as cache_mod


# ── Test doubles ─────────────────────────────────────────────────────────


class _FakeRedis:
    """In-memory async Redis double supporting get/incr on string values."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.incr_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def incr(self, key: str) -> int:
        self.incr_calls.append(key)
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])


class _ExplodingRedis:
    """Redis double that always raises on incr, simulating a Redis outage."""

    async def incr(self, key: str) -> int:
        raise RuntimeError("redis down")


# ── bump_kb_caches ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bump_kb_caches_increments_both_namespaces(monkeypatch):
    """A KB write must bump ``knowledge`` AND ``semantic_cache`` together so the
    semantic cache cannot serve stale facts after a future enablement."""
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    await cache_mod.bump_kb_caches()

    assert "cachever:knowledge" in redis.incr_calls
    assert "cachever:semantic_cache" in redis.incr_calls
    # Both bumped exactly once, in order (knowledge first, then semantic_cache).
    assert redis.incr_calls == ["cachever:knowledge", "cachever:semantic_cache"]


@pytest.mark.asyncio
async def test_bump_kb_caches_is_best_effort_on_redis_outage(monkeypatch):
    """A Redis failure must not surface to the KB-write caller (best-effort)."""
    monkeypatch.setattr(cache_mod, "get_redis", lambda: _ExplodingRedis())

    # Must not raise — the cache layer is best-effort by contract.
    await cache_mod.bump_kb_caches()


@pytest.mark.asyncio
async def test_bump_cache_version_increments_namespace(monkeypatch):
    """The primitive helper increments the named namespace's version counter."""
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    await cache_mod.bump_cache_version("knowledge")
    await cache_mod.bump_cache_version("knowledge")

    assert redis._store["cachever:knowledge"] == "2"


@pytest.mark.asyncio
async def test_cache_version_returns_string_default(monkeypatch):
    """cache_version returns the stored value or '1' default (never None)."""
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    # Default when the key does not exist yet.
    assert await cache_mod.cache_version("unknown") == "1"

    # Reflects bumps.
    await cache_mod.bump_cache_version("known")
    assert await cache_mod.cache_version("known") == "1"
