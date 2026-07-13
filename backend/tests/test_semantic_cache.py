"""Tests for the semantic cache (Phase 5).

The cosine similarity + disabled-path logic is pure-Python and fully testable.
The Redis store/scan path is integration-level and covered by the existing
``no_cache_io`` test fixtures in test_graph_tools when the flag is on.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.graph import semantic_cache as sc


# --- _cosine (pure) ----------------------------------------------------------


def test_cosine_identical_vectors_is_one():
    assert sc._cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero():
    assert sc._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_vectors_is_negative_one():
    assert sc._cosine([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)


def test_cosine_empty_or_mismatched_returns_zero():
    assert sc._cosine([], []) == 0.0
    assert sc._cosine([1.0], [1.0, 2.0]) == 0.0


def test_cosine_zero_vector_returns_zero():
    assert sc._cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_partial_similarity_in_range():
    """Two similar-but-not-identical vectors produce a value in (0, 1)."""
    sim = sc._cosine([1.0, 1.0, 1.0], [1.0, 1.0, 0.5])
    assert 0.0 < sim < 1.0


# --- disabled-path (flag gating) --------------------------------------------


async def test_semantic_cache_get_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(semantic_cache_enabled=False))
    result = await sc.semantic_cache_get([1.0, 2.0])
    assert result is None


async def test_semantic_cache_put_noop_when_disabled(monkeypatch):
    """When disabled, put must not touch Redis at all."""
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(semantic_cache_enabled=False))
    # If this tried Redis it would raise (no connection); not raising = correct.
    await sc.semantic_cache_put([1.0, 2.0], "result")


async def test_semantic_cache_get_swallows_redis_errors(monkeypatch):
    """A Redis failure must return None, never raise (best-effort contract)."""
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(semantic_cache_enabled=True))

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(sc, "_keys", _boom)
    result = await sc.semantic_cache_get([1.0, 2.0])
    assert result is None


# --- SemanticCacheHit dataclass ---------------------------------------------


def test_semantic_cache_hit_is_frozen():
    hit = sc.SemanticCacheHit(result="x", similarity=0.96, cached_query="hash")
    assert hit.result == "x"
    assert hit.similarity == 0.96
    with pytest.raises(Exception):  # frozen dataclass
        hit.result = "y"


# --- bump_semantic_cache_version -------------------------------------------


async def test_bump_semantic_cache_version_delegates_to_bump(monkeypatch):
    """The standalone bump helper must delegate to bump_cache_version('semantic_cache').

    This is the helper KB-write paths could call directly; the production path
    goes through bump_kb_caches() (tested in test_core_cache.py), but this guard
    pins the delegation so a refactor cannot silently drop the namespace.
    """
    bumped: list[str] = []

    async def _fake_bump(namespace: str) -> None:
        bumped.append(namespace)

    # The import happens inside the function, so patch at the source module.
    import app.core.cache as cache_mod

    monkeypatch.setattr(cache_mod, "bump_cache_version", _fake_bump)

    await sc.bump_semantic_cache_version()

    assert bumped == ["semantic_cache"]


async def test_bump_semantic_cache_version_swallows_errors(monkeypatch):
    """A Redis/cache failure must return None, never raise (best-effort contract)."""
    import app.core.cache as cache_mod

    async def _boom(namespace: str) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(cache_mod, "bump_cache_version", _boom)

    # Must not raise.
    await sc.bump_semantic_cache_version()


# --- false-positive / cross-topic / cross-project rejection ------------------
# Phase 3-RAG.2: before enabling the semantic cache, prove that distinct-topic
# and cross-project queries do NOT hit each other. These exercise the full
# Redis store/scan path with an in-memory fake Redis (no live Redis required).


class _FakeHashRedis:
    """In-memory async Redis double supporting the HASH/ZSET/pipeline ops that
    the semantic cache uses (hgetall/hset/hget/zadd/zcard/zrange/zrem/expire)."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._zsets: dict[str, dict[str, float]] = {}

    def pipeline(self):
        ops: list[tuple] = []

        class _Pipe:
            def hset(_self, key, field, value):
                ops.append(("hset", key, field, value))
                return _self

            def zadd(_self, key, mapping):
                ops.append(("zadd", key, mapping))
                return _self

            def expire(_self, key, ttl):
                ops.append(("expire", key, ttl))
                return _self

            def hdel(_self, key, *fields):
                ops.append(("hdel", key, fields))
                return _self

            def zrem(_self, key, *members):
                ops.append(("zrem", key, members))
                return _self

            async def execute(_self):
                for op in ops:
                    if op[0] == "hset":
                        _, key, field, value = op
                        self._hashes.setdefault(key, {})[field] = value
                    elif op[0] == "zadd":
                        _, key, mapping = op
                        z = self._zsets.setdefault(key, {})
                        for member, score in mapping.items():
                            z[member] = float(score)
                    # hdel/zrem/expire are no-ops in the fake (not needed for
                    # false-positive tests; LRU eviction has its own path).

        return _Pipe()

    async def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    async def zcard(self, key):
        return len(self._zsets.get(key, {}))

    async def zrange(self, key, start, stop):
        members = sorted(self._zsets.get(key, {}), key=lambda m: self._zsets[key][m])
        return members[start : stop + 1] if stop >= 0 else members[start:]


async def _enabled_settings(monkeypatch, **overrides):
    """Flip the semantic cache ON and wire a fake Redis."""
    from types import SimpleNamespace

    fake_redis = _FakeHashRedis()
    defaults = dict(
        semantic_cache_enabled=True,
        semantic_cache_threshold=0.95,
        semantic_cache_capacity=200,
        semantic_cache_ttl_seconds=1800,
    )
    defaults.update(overrides)
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(**defaults))

    # _keys returns a tuple (vkey, rkey, tkey). Patch to fixed keys so the fake
    # Redis stores land in known buckets.
    async def _async_keys():
        return ("sc:1:vecs", "sc:1:results", "sc:1:ts")

    monkeypatch.setattr(sc, "_keys", _async_keys)

    # Patch get_redis in the redis module the cache imports lazily.
    import app.core.redis as redis_mod

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
    return fake_redis


async def test_semantic_cache_rejects_distinct_topic_query(monkeypatch):
    """A query about salary must NOT hit a cached entry about the shuttle bus.

    Distinct topics have near-orthogonal embeddings; the 0.95 threshold must
    reject them. This is the core false-positive guard before enabling the cache.
    """
    await _enabled_settings(monkeypatch)

    # Salary query and shuttle query: orthogonal unit vectors (cosine = 0.0).
    salary_vec = [1.0, 0.0, 0.0]
    shuttle_vec = [0.0, 1.0, 0.0]
    await sc.semantic_cache_put(salary_vec, "Lương 15 triệu/tháng.")

    # A NEW query about the shuttle must NOT return the salary answer.
    hit = await sc.semantic_cache_get(shuttle_vec)
    assert hit is None, (
        "semantic cache false positive: a shuttle-bus query returned a salary answer"
    )


async def test_semantic_cache_rejects_below_threshold_near_match(monkeypatch):
    """A similar-but-not-identical query below the 0.95 threshold must miss."""
    await _enabled_settings(monkeypatch, semantic_cache_threshold=0.95)

    cached_vec = [1.0, 1.0, 1.0]
    # Cosine(cached, query) = (1+1+0)/(sqrt(3)*sqrt(2)) ≈ 0.816 < 0.95
    query_vec = [1.0, 1.0, 0.0]
    await sc.semantic_cache_put(cached_vec, "câu trả lời A")

    hit = await sc.semantic_cache_get(query_vec)
    assert hit is None, (
        "semantic cache hit at cos≈0.816, below the 0.95 floor — expected a miss"
    )


async def test_semantic_cache_hits_on_near_identical_query(monkeypatch):
    """Sanity check: a paraphrase whose embedding is ~identical DOES hit.

    This proves the rejection tests above fail because of the threshold, not a
    wiring bug in the fake Redis.
    """
    await _enabled_settings(monkeypatch, semantic_cache_threshold=0.95)

    cached_vec = [1.0, 2.0, 3.0]
    # Identical vector → cosine = 1.0, well above threshold.
    await sc.semantic_cache_put(cached_vec, "câu trả lời gốc")

    hit = await sc.semantic_cache_get([1.0, 2.0, 3.0])
    assert hit is not None
    assert hit.result == "câu trả lời gốc"
    assert hit.similarity == pytest.approx(1.0)


async def test_semantic_cache_empty_returns_none(monkeypatch):
    """An empty cache must return None (miss), not raise."""
    await _enabled_settings(monkeypatch)

    hit = await sc.semantic_cache_get([1.0, 0.0, 0.0])
    assert hit is None

