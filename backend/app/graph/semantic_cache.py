"""Semantic cache for non-personalized knowledge queries (Phase 5).

The exact-hash RAG cache (``rag:knowledge:{sha(...)} ``) misses on paraphrased queries
("lương bao nhiêu" vs "mức lương là"). This adds a similarity-based layer: embed the
query, check it against a small Redis-backed ring of recent query embeddings, and
return the cached result if cosine similarity exceeds a conservative threshold.

**Scope discipline (critical):** only non-personalized ``search_knowledge`` queries
are cached. Recommendation / profile / memory queries are never cached semantically
because the result depends on the specific candidate's lead profile, not just the
query text. The caller (``search_knowledge``) enforces this by being the only wiring
point; ``recommend_jobs`` / ``search_user_memory`` never call this module.

Implementation is a linear scan over a Redis HASH of recent entries (query vector →
result). A full HNSW in Redis is YAGNI at current query volumes; the ring is capped
at ``semantic_cache_capacity`` entries with LRU eviction via a sorted-set timestamp.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Redis structures (all under these keys, namespaced by version for global flush):
#   semantic_cache:v{ver}:vecs   — HASH field=query_hash -> JSON vector list
#   semantic_cache:v{ver}:results — HASH field=query_hash -> result text
#   semantic_cache:v{ver}:ts     — ZSET member=query_hash -> epoch seconds (LRU eviction)
_VEC_KEY = "semantic_cache:{ver}:vecs"
_RESULT_KEY = "semantic_cache:{ver}:results"
_TS_KEY = "semantic_cache:{ver}:ts"


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for two equal-length vectors (0.0 on length mismatch)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


@dataclass(frozen=True)
class SemanticCacheHit:
    result: str
    similarity: float
    cached_query: str


def _settings():
    from app.core.config import get_settings

    return get_settings()


async def _keys() -> tuple[str, str, str]:
    from app.core.cache import cache_version

    ver = await cache_version("semantic_cache")
    return _VEC_KEY.format(ver=ver), _RESULT_KEY.format(ver=ver), _TS_KEY.format(ver=ver)


async def semantic_cache_get(
    query_vec: list[float], *, threshold: float | None = None
) -> SemanticCacheHit | None:
    """Return a cached result if a similar query exceeds the similarity threshold.

    Linear scan over the stored query vectors. Returns ``None`` on miss, disabled,
    or any Redis error (best-effort, non-fatal).
    """
    import json

    from app.core.redis import get_redis

    s = _settings()
    if not getattr(s, "semantic_cache_enabled", False):
        return None
    thr = threshold if threshold is not None else getattr(s, "semantic_cache_threshold", 0.95)
    try:
        vkey, rkey, _tkey = await _keys()
        r = await get_redis()
        all_vecs = await r.hgetall(vkey)
        if not all_vecs:
            return None
        best_hit: SemanticCacheHit | None = None
        best_sim = 0.0
        for qhash, vec_json in all_vecs.items():
            try:
                cached_vec = json.loads(vec_json)
            except (json.JSONDecodeError, TypeError):
                continue
            sim = _cosine(query_vec, cached_vec)
            # Only advance best_sim when a qualifying hit is actually recorded,
            # so a stale/missing higher-similarity entry can't mask a valid lower one.
            if sim >= thr and sim > best_sim:
                result = await r.hget(rkey, qhash)
                if result:
                    best_sim = sim
                    best_hit = SemanticCacheHit(result=result, similarity=sim, cached_query=qhash)
        return best_hit
    except Exception:  # noqa: BLE001
        logger.debug("semantic cache get failed (non-fatal)", exc_info=True)
        return None


async def semantic_cache_put(query_vec: list[float], result: str) -> None:
    """Store a query vector + result for future similarity matches.

    Enforces LRU eviction at ``semantic_cache_capacity``. Best-effort, non-fatal.
    """
    import json

    from app.core.redis import get_redis

    s = _settings()
    if not getattr(s, "semantic_cache_enabled", False):
        return
    cap = getattr(s, "semantic_cache_capacity", 200)
    ttl = getattr(s, "semantic_cache_ttl_seconds", 1800)
    try:
        from hashlib import sha256

        # The hash is over the vector to dedupe near-identical queries that would
        # otherwise bloat the ring; the similarity scan still uses the raw vector.
        qhash = sha256(json.dumps([round(v, 6) for v in query_vec]).encode()).hexdigest()[:32]
        r = await get_redis()
        vkey, rkey, tkey = await _keys()
        pipe = r.pipeline()
        pipe.hset(vkey, qhash, json.dumps(query_vec))
        pipe.hset(rkey, qhash, result)
        pipe.zadd(tkey, {qhash: time.time()})
        pipe.expire(vkey, ttl)
        pipe.expire(rkey, ttl)
        pipe.expire(tkey, ttl)
        await pipe.execute()

        # LRU eviction: if over capacity, remove the oldest entries.
        count = await r.zcard(tkey)
        if count > cap:
            overflow = count - cap
            oldest = await r.zrange(tkey, 0, overflow - 1)
            if oldest:
                pipe = r.pipeline()
                for member in oldest:
                    pipe.hdel(vkey, member)
                    pipe.hdel(rkey, member)
                    pipe.zrem(tkey, member)
                await pipe.execute()
    except Exception:  # noqa: BLE001
        logger.debug("semantic cache put failed (non-fatal)", exc_info=True)


async def bump_semantic_cache_version() -> None:
    """Invalidate the whole semantic cache (e.g. on KB content change)."""
    try:
        from app.core.cache import bump_cache_version

        await bump_cache_version("semantic_cache")
    except Exception:  # noqa: BLE001
        logger.debug("semantic cache version bump failed (non-fatal)", exc_info=True)
