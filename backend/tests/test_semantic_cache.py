"""Tests for the semantic cache (Phase 5).

The cosine similarity + disabled-path logic is pure-Python and fully testable.
The Redis store/scan path runs against an in-memory fake Redis while keeping the
real ``_keys`` (version + scope namespace) derivation, so the scope isolation
between two Pages is covered end to end.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.graph import semantic_cache as sc
from tests.helpers.redis_fake import FakeHashRedis


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
    result = await sc.semantic_cache_get([1.0, 2.0], scope="global")
    assert result is None


async def test_semantic_cache_put_noop_when_disabled(monkeypatch):
    """When disabled, put must not touch Redis at all."""
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(semantic_cache_enabled=False))
    # If this tried Redis it would raise (no connection); not raising = correct.
    await sc.semantic_cache_put([1.0, 2.0], "result", scope="global")


async def test_semantic_cache_get_swallows_redis_errors(monkeypatch):
    """A Redis failure must return None, never raise (best-effort contract)."""
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(semantic_cache_enabled=True))

    async def _boom(_scope):
        raise RuntimeError("redis down")

    monkeypatch.setattr(sc, "_keys", _boom)
    result = await sc.semantic_cache_get([1.0, 2.0], scope="global")
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


async def _enabled_settings(monkeypatch, **overrides):
    """Flip the semantic cache ON and wire a fake Redis.

    ``_keys`` is left REAL (only the cache-version read is pinned), so the tests
    exercise the production key path — including the scope namespace that keeps
    two retrieval scopes from reading each other's answers.
    """
    from types import SimpleNamespace

    fake_redis = FakeHashRedis()
    defaults = dict(
        semantic_cache_enabled=True,
        semantic_cache_threshold=0.95,
        semantic_cache_capacity=200,
        semantic_cache_ttl_seconds=1800,
    )
    defaults.update(overrides)
    monkeypatch.setattr(sc, "_settings", lambda: SimpleNamespace(**defaults))

    # ``_keys`` imports cache_version lazily from app.core.cache.
    import app.core.cache as cache_mod

    async def _pinned_version(_namespace):
        return "1"

    monkeypatch.setattr(cache_mod, "cache_version", _pinned_version)

    # Patch get_redis in the redis module the cache imports lazily.
    import app.core.redis as redis_mod

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
    return fake_redis


def _scope(*project_ids: str, top_k: int = 25) -> str:
    """Scope token for one Page's assigned projects (the production derivation)."""
    return sc.scope_key(list(project_ids), top_k)


async def test_semantic_cache_rejects_distinct_topic_query(monkeypatch):
    """A query about salary must NOT hit a cached entry about the shuttle bus.

    Distinct topics have near-orthogonal embeddings; the 0.95 threshold must
    reject them. This is the core false-positive guard before enabling the cache.
    """
    await _enabled_settings(monkeypatch)

    # Salary query and shuttle query: orthogonal unit vectors (cosine = 0.0).
    salary_vec = [1.0, 0.0, 0.0]
    shuttle_vec = [0.0, 1.0, 0.0]
    await sc.semantic_cache_put(salary_vec, "Lương 15 triệu/tháng.", scope=_scope("proj-a"))

    # A NEW query about the shuttle must NOT return the salary answer.
    hit = await sc.semantic_cache_get(shuttle_vec, scope=_scope("proj-a"))
    assert hit is None, (
        "semantic cache false positive: a shuttle-bus query returned a salary answer"
    )


async def test_semantic_cache_rejects_below_threshold_near_match(monkeypatch):
    """A similar-but-not-identical query below the 0.95 threshold must miss."""
    await _enabled_settings(monkeypatch, semantic_cache_threshold=0.95)

    cached_vec = [1.0, 1.0, 1.0]
    # Cosine(cached, query) = (1+1+0)/(sqrt(3)*sqrt(2)) ≈ 0.816 < 0.95
    query_vec = [1.0, 1.0, 0.0]
    await sc.semantic_cache_put(cached_vec, "câu trả lời A", scope=_scope("proj-a"))

    hit = await sc.semantic_cache_get(query_vec, scope=_scope("proj-a"))
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
    await sc.semantic_cache_put(cached_vec, "câu trả lời gốc", scope=_scope("proj-a"))

    hit = await sc.semantic_cache_get([1.0, 2.0, 3.0], scope=_scope("proj-a"))
    assert hit is not None
    assert hit.result == "câu trả lời gốc"
    assert hit.similarity == pytest.approx(1.0)


async def test_semantic_cache_empty_returns_none(monkeypatch):
    """An empty cache must return None (miss), not raise."""
    await _enabled_settings(monkeypatch)

    hit = await sc.semantic_cache_get([1.0, 0.0, 0.0], scope=_scope("proj-a"))
    assert hit is None


async def test_new_writes_do_not_extend_an_older_entry_lifetime(monkeypatch):
    await _enabled_settings(monkeypatch, semantic_cache_ttl_seconds=10)
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: clock[0])
    scope = _scope("proj-a")
    await sc.semantic_cache_put([1.0, 0.0], "old salary", scope=scope)
    clock[0] = 1009
    await sc.semantic_cache_put([0.0, 1.0], "fresh shuttle", scope=scope)
    clock[0] = 1010

    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is None
    hit = await sc.semantic_cache_get([0.0, 1.0], scope=scope)
    assert hit is not None and hit.result == "fresh shuttle"


async def test_custom_entry_ttl_is_respected_without_changing_default(monkeypatch):
    await _enabled_settings(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: clock[0])
    scope = _scope("proj-a")
    await sc.semantic_cache_put([1.0, 0.0], "short lived", scope=scope, ttl_seconds=5)
    clock[0] = 1005

    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is None


async def test_expired_best_match_does_not_mask_a_fresh_match(monkeypatch):
    await _enabled_settings(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: clock[0])
    scope = _scope("proj-a")
    await sc.semantic_cache_put([1.0, 0.0], "expired", scope=scope, ttl_seconds=5)
    clock[0] = 1004
    await sc.semantic_cache_put([1.0, 0.01], "current", scope=scope)
    clock[0] = 1006

    hit = await sc.semantic_cache_get([1.0, 0.0], scope=scope)
    assert hit is not None and hit.result == "current"


async def test_reads_update_lru_without_extending_entry_expiry(monkeypatch):
    await _enabled_settings(monkeypatch, semantic_cache_capacity=2, semantic_cache_ttl_seconds=10)
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "time", lambda: clock[0])
    scope = _scope("proj-a")
    await sc.semantic_cache_put([1.0, 0.0], "A", scope=scope)
    clock[0] = 1001
    await sc.semantic_cache_put([0.0, 1.0], "B", scope=scope)
    clock[0] = 1002
    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is not None
    clock[0] = 1003
    await sc.semantic_cache_put([-1.0, 0.0], "C", scope=scope)

    assert await sc.semantic_cache_get([0.0, 1.0], scope=scope) is None
    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is not None
    clock[0] = 1010
    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is None


async def test_legacy_entry_without_a_lifetime_is_a_cache_miss(monkeypatch):
    fake = await _enabled_settings(monkeypatch)
    scope = _scope("proj-a")
    vkey, rkey, _ = await sc._keys(scope)
    pipe = fake.pipeline()
    pipe.hset(vkey, "legacy", sc.pack_vector([1.0, 0.0]))
    pipe.hset(rkey, "legacy", "old facts with no expiry")
    await pipe.execute()

    assert await sc.semantic_cache_get([1.0, 0.0], scope=scope) is None


# --- scope namespacing (REL-07) ---------------------------------------------


def test_scope_key_is_stable_and_order_independent():
    """The token must not depend on DB row order, but must separate scopes."""
    assert sc.scope_key(["b", "a"], 25) == sc.scope_key(["a", "b"], 25)
    assert sc.scope_key(["a"], 25) != sc.scope_key(["b"], 25)
    assert sc.scope_key(["a"], 25) != sc.scope_key(["a"], 5)  # top_k changes the answer
    assert sc.scope_key(None) == "global"  # no project scope exposed by the port
    assert sc.scope_key(None, 25) != sc.scope_key(None, 5)
    assert sc.scope_key([]) != "global"  # an empty-but-known scope is its own namespace


def test_keys_include_version_and_scope(monkeypatch):
    """The Redis keys carry both the flush version and the scope namespace."""
    import asyncio

    import app.core.cache as cache_mod

    async def _pinned_version(_namespace):
        return "7"

    monkeypatch.setattr(cache_mod, "cache_version", _pinned_version)

    vkey, rkey, tkey = asyncio.run(sc._keys("abc123"))

    assert vkey == "semantic_cache:7:abc123:vecs"
    assert rkey == "semantic_cache:7:abc123:results"
    assert tkey == "semantic_cache:7:abc123:ts"


async def test_semantic_cache_page_scopes_do_not_share_entries(monkeypatch):
    """REL-07 acceptance: a Page-scoped lookup cannot read another Page's answer.

    Both Pages reach the cache with ``project_slug=None`` (no slug was passed) and
    a non-empty ``project_ids``, so only the scope namespace separates them: a
    Page-B lookup must MISS the identical query cached for Page A, while Page A
    itself still hits.
    """
    await _enabled_settings(monkeypatch)

    page_a = _scope("proj-a", "proj-b")
    page_b = _scope("proj-c")
    query_vec = [1.0, 2.0, 3.0]

    await sc.semantic_cache_put(query_vec, "câu trả lời của Trang A", scope=page_a)

    hit_b = await sc.semantic_cache_get(query_vec, scope=page_b)
    assert hit_b is None, "Page B was served an answer cached for Page A's catalog"

    hit_a = await sc.semantic_cache_get(query_vec, scope=page_a)
    assert hit_a is not None
    assert hit_a.result == "câu trả lời của Trang A"


async def test_semantic_cache_scan_runs_off_the_event_loop(monkeypatch):
    """The decode + cosine scan must not run on the loop (REL-07).

    A full ring is ``capacity`` vectors × ``embedding_dim`` floats of pure-Python
    arithmetic; running it inline stalls every concurrent request.
    """
    import threading

    await _enabled_settings(monkeypatch)
    scope = _scope("proj-a")
    await sc.semantic_cache_put([1.0, 0.0, 0.0], "câu trả lời", scope=scope)

    scan_threads: list[threading.Thread] = []
    real_scan = sc._scan_candidates

    def _spy(query_vec, stored, threshold):
        scan_threads.append(threading.current_thread())
        return real_scan(query_vec, stored, threshold)

    monkeypatch.setattr(sc, "_scan_candidates", _spy)

    hit = await sc.semantic_cache_get([1.0, 0.0, 0.0], scope=scope)

    assert hit is not None and hit.result == "câu trả lời"  # the scan still works
    assert scan_threads, "the scan never ran"
    assert scan_threads[0] is not threading.main_thread(), "the scan ran on the event loop"


async def test_semantic_cache_skips_undecodable_vectors(monkeypatch):
    """A corrupt/legacy value is a miss for that entry, never an exception."""
    fake = await _enabled_settings(monkeypatch)
    scope = _scope("proj-a")
    vkey, rkey, _tkey = await sc._keys(scope)
    # A pre-scope JSON-array entry (the old wire format) sitting in the ring.
    pipe = fake.pipeline()
    pipe.hset(vkey, "legacy", "[1.0, 0.0, 0.0]")
    pipe.hset(rkey, "legacy", "câu trả lời cũ")
    await pipe.execute()

    hit = await sc.semantic_cache_get([1.0, 0.0, 0.0], scope=scope)

    assert hit is None


# --- end to end: search_knowledge namespaces the cache per retrieval scope ---


class _SearchSettings:
    """Settings stand-in for ``search_knowledge`` with the semantic cache on."""

    rag_cache_enabled = True
    rag_result_cache_ttl_seconds = 60
    semantic_cache_enabled = True
    semantic_cache_threshold = 0.95
    semantic_cache_capacity = 200
    semantic_cache_ttl_seconds = 1800
    singleflight_enabled = False
    embedding_provider = "openrouter"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    gemini_embedding_model = "gemini-embedding-2"
    embedding_dim = 3
    embedding_cache_ttl_seconds = 60


def _knowledge_row(text: str):
    return SimpleNamespace(
        id=text,
        content=text,
        source_quote=text,
        summary=None,
        metadata={},
        source_file=None,
        line_start=None,
        line_end=None,
    )


def _page_repo(project_id: str, answer: str):
    """Fake retrieval port for one Page: its own project scope + its own catalog."""
    from tests.test_graph_tools import _const, _make_repo

    return _make_repo(
        active_project_ids=lambda self: _const([project_id]),
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, flags, *, project_ids=None, query_text="": _const(
            [_knowledge_row(answer)]
        ),
    )


async def test_search_knowledge_page_scope_never_returns_another_pages_answer(monkeypatch):
    """REL-07 acceptance, end to end.

    Both Pages arrive with ``project_slug=None`` and a non-empty ``project_ids``
    (their Page's assigned Projects) and ask the *same* question, so their
    embeddings are identical. Only the scope namespace in the cache key keeps
    Page B from being answered out of Page A's catalog.
    """
    from tests.test_graph_tools import _FakeEmbedder, _patch_tool_io

    from app.graph.tools.knowledge import search_knowledge

    await _enabled_settings(monkeypatch)
    _patch_tool_io(monkeypatch, _SearchSettings)

    embedder = _FakeEmbedder(vec=[1.0, 0.0, 0.0])

    out_a = await search_knowledge(
        retrieval=_page_repo("proj-a", "Trang A: lương 15 triệu"),
        embedder=embedder,
        query="lương bao nhiêu",
    )
    assert "Trang A" in out_a

    out_b = await search_knowledge(
        retrieval=_page_repo("proj-b", "Trang B: lương 12 triệu"),
        embedder=embedder,
        query="lương bao nhiêu",
    )

    assert "Trang B" in out_b
    assert "Trang A" not in out_b, "Page B was served an answer cached for Page A"


async def test_retrieval_finishing_after_invalidation_does_not_seed_the_new_generation(monkeypatch):
    import app.core.cache as cache_mod
    import app.graph.tools.knowledge as knowledge
    from tests.test_graph_tools import _FakeEmbedder, _patch_tool_io

    class Settings(_SearchSettings):
        rag_cache_enabled = False

    await _enabled_settings(monkeypatch)
    _patch_tool_io(monkeypatch, Settings)
    generation = ["1"]

    async def current_version(_namespace):
        return generation[0]

    monkeypatch.setattr(cache_mod, "cache_version", current_version)
    monkeypatch.setattr(knowledge, "cache_version", current_version)
    repo = _page_repo("proj-a", "unused")
    calls = []

    async def documents(emb, top_k, flags, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            generation[0] = "2"  # A KB update commits while the old read finishes.
            return [_knowledge_row("OLD salary")]
        return [_knowledge_row("NEW salary")]

    repo.match_documents = documents
    embedder = _FakeEmbedder(vec=[1.0, 0.0, 0.0])
    first = await knowledge.search_knowledge(repo, embedder, "salary before update")
    second = await knowledge.search_knowledge(repo, embedder, "salary after update")

    assert "OLD salary" in first
    assert "NEW salary" in second and "OLD salary" not in second
    assert len(calls) == 2
