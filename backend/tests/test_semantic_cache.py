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

