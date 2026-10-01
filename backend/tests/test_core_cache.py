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

    async def set(self, key: str, value: str, *, nx: bool = False) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def incr(self, key: str) -> int:
        self.incr_calls.append(key)
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])


class _ExplodingRedis:
    """Redis double that always raises, simulating a Redis outage."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, *, nx: bool = False) -> bool:
        raise RuntimeError("redis down")

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

    # Both namespaces are seeded at a fresh generation (never a small value
    # that could match pre-loss v{n} entries).
    assert int(redis._store["cachever:knowledge"]) > 10**9
    assert int(redis._store["cachever:semantic_cache"]) > 10**9


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
    first = redis._store["cachever:knowledge"]
    await cache_mod.bump_cache_version("knowledge")
    second = redis._store["cachever:knowledge"]

    # First bump seeds a fresh generation; every later bump is a pure INCR.
    assert int(first) > 10**9  # seeded generation, not a small counter restart
    assert int(second) == int(first) + 1


@pytest.mark.asyncio
async def test_cache_version_seeds_fresh_generation_on_miss(monkeypatch):
    """A missing counter is a FULL FLUSH, never a reset to "1".

    Returning a small default after the counter is lost (eviction, flush) can
    match still-live v{n} entries written before the loss and resurrect stale
    cache data. The seeded generation must be larger than any INCR counter the
    namespace ever carried, must be persisted so all processes agree, and must
    be stable across reads — an unstable version would break cache hits.
    """
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    first = await cache_mod.cache_version("unknown")
    second = await cache_mod.cache_version("unknown")

    assert int(first) > 10**9  # beyond any legacy small counter, so nothing matches
    assert first == second  # stable: persisted, not re-seeded per call
    assert redis._store["cachever:unknown"] == first


@pytest.mark.asyncio
async def test_cache_version_returns_present_counter_verbatim(monkeypatch):
    """A present counter is returned as stored — INCR semantics untouched."""
    redis = _FakeRedis()
    redis._store["cachever:known"] = "7"
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    assert await cache_mod.cache_version("known") == "7"


@pytest.mark.asyncio
async def test_cache_version_outage_returns_fresh_generation_not_one(monkeypatch):
    """During a Redis outage the returned value must never be "1".

    The cache reads/writes that would use this value fail too (nothing stale
    can be served through it), but a small constant could resurrect old v{n}
    entries once Redis recovers with the counter still missing.
    """
    monkeypatch.setattr(cache_mod, "get_redis", lambda: _ExplodingRedis())

    value = await cache_mod.cache_version("knowledge")

    assert value != "1"
    assert int(value) > 10**9


# ── KB content mutation → cache invalidation contract ────────────────────


@pytest.mark.asyncio
async def test_bump_kb_caches_invalidates_both_cache_namespaces(monkeypatch):
    """A KB mutation must invalidate BOTH the exact-hash RAG cache and the
    semantic cache.

    The exact-hash RAG cache key embeds ``cache_version("knowledge")``; the
    semantic cache namespace reads ``cache_version("semantic_cache")``. After a
    KB write, both versions must have advanced so neither cache can serve a
    stale FAQ/knowledge answer. This pins the Phase 1.5 correctness gate:
    'KB updates cannot serve a stale FAQ answer'.
    """
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    kv_before = await cache_mod.cache_version("knowledge")
    sv_before = await cache_mod.cache_version("semantic_cache")

    # Simulate a NEW KB content mutation (FAQ create/update/delete, doc ingest,
    # version activate, archive — all now call bump_kb_caches()).
    await cache_mod.bump_kb_caches()

    kv_after = await cache_mod.cache_version("knowledge")
    sv_after = await cache_mod.cache_version("semantic_cache")

    # Both must advance — a stale version on either namespace would let the
    # corresponding cache serve pre-mutation content.
    assert int(kv_after) > int(kv_before), (
        f"knowledge version did not advance after KB mutation ({kv_before} → {kv_after}); "
        "the exact-hash RAG cache could serve stale answers"
    )
    assert int(sv_after) > int(sv_before), (
        f"semantic_cache version did not advance after KB mutation ({sv_before} → {sv_after}); "
        "the semantic RAG cache could serve stale answers"
    )


@pytest.mark.asyncio
async def test_first_bump_after_counter_loss_never_restarts_small(monkeypatch):
    """A bump on an absent namespace must seed a fresh generation.

    Recreating a lost counter at "2" (the pre-flush-on-miss behaviour) would
    make still-live stale v2 entries readable again — the resurrection bug
    PERF-02 describes. Seeding at epoch scale makes every historical v{n}
    entry unreachable at once.
    """
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    assert await cache_mod.bump_cache_version("fresh") is True
    seeded = redis._store["cachever:fresh"]
    assert int(seeded) > 10**9

    await cache_mod.bump_cache_version("fresh")
    assert int(redis._store["cachever:fresh"]) == int(seeded) + 1
    assert await cache_mod.cache_version("fresh") == str(int(seeded) + 1)


async def test_counter_loss_within_one_second_does_not_resurrect_entries(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)
    monkeypatch.setattr("time.time", lambda: 1_800_000_000)

    first = await cache_mod.cache_version("knowledge")
    redis._store.pop("cachever:knowledge")
    second = await cache_mod.cache_version("knowledge")

    assert first != second


async def test_counter_seed_loser_adopts_the_winning_generation(monkeypatch):
    class RacingRedis(_FakeRedis):
        async def set(self, key, value, *, nx=False):
            if nx:
                self._store[key] = "777"
                return False
            return await super().set(key, value, nx=nx)

    redis = RacingRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)

    assert await cache_mod.cache_version("knowledge") == "777"


async def test_lost_counter_bump_cannot_reuse_the_previous_generation(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, "get_redis", lambda: redis)
    monkeypatch.setattr("time.time", lambda: 1_800_000_000)

    first = await cache_mod.cache_version("knowledge")
    redis._store.pop("cachever:knowledge")
    assert await cache_mod.bump_cache_version("knowledge") is True

    assert await cache_mod.cache_version("knowledge") != first
