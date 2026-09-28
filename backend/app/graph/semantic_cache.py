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

Every entry is namespaced by the retrieval scope it was computed under (see
:func:`scope_key`). A Page-scoped conversation reaches ``search_knowledge`` with
``project_slug=None`` and a non-empty ``project_ids`` (its Page's assigned
Projects), so "unscoped" is NOT the same as "the deployment-wide catalog": without
the scope in the key, a Page-scoped turn could be served an answer computed against
a different Page's catalog.

Implementation is a linear scan over a Redis HASH of recent entries (query vector →
result). A full HNSW in Redis is YAGNI at current query volumes; the ring is capped
at ``semantic_cache_capacity`` entries with LRU eviction via a sorted-set timestamp.
Vectors are stored as packed base64 float16 (the wire format ``graph.tools._shared``
uses for the embedding cache), and the decode + cosine scan runs on a worker thread
so a full ring never stalls the event loop.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import time
from dataclasses import dataclass
from hashlib import sha256

logger = logging.getLogger(__name__)

# Redis structures (all under these keys, namespaced by version for global flush
# and by retrieval scope so two Pages can never read each other's answers):
#   semantic_cache:v{ver}:{scope}:vecs    — HASH field=query_hash -> packed vector
#   semantic_cache:v{ver}:{scope}:results — HASH field=query_hash -> result text
#   semantic_cache:v{ver}:{scope}:ts      — ZSET member=query_hash -> epoch seconds
_VEC_KEY = "semantic_cache:{ver}:{scope}:vecs"
_RESULT_KEY = "semantic_cache:{ver}:{scope}:results"
_TS_KEY = "semantic_cache:{ver}:{scope}:ts"

# Namespace for the deployment-wide catalog (a port that exposes no project scope).
_SCOPE_GLOBAL = "global"


def scope_key(project_ids: list[str] | None, top_k: int | None = None) -> str:
    """Return the cache namespace token for one retrieval scope.

    ``project_ids`` is the exact project scope the answer was retrieved under
    (sorted here as well, so row order can never leak into the token).
    ``project_ids is None`` means the retrieval port exposes no project scope at
    all — the deployment-wide catalog. ``top_k`` is part of the token for the same
    reason it is part of the exact-hash RAG key: it changes how many chunks the
    answer is built from, so it changes the answer.
    """
    if project_ids is None:
        return _SCOPE_GLOBAL
    digest = sha256("\x1f".join(sorted(str(pid) for pid in project_ids)).encode("utf-8"))
    if top_k is not None:
        digest.update(f"\x1f{int(top_k)}".encode("utf-8"))
    return digest.hexdigest()[:16]


def _pack_vector(vector: list[float]) -> str:
    """Pack a vector as base64 float16 (same wire format as the embed cache)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def _unpack_vector(payload: object) -> list[float] | None:
    """Decode a packed vector; ``None`` for anything undecodable (a miss, not an error)."""
    if not isinstance(payload, str) or not payload:
        return None
    try:
        blob = base64.b64decode(payload, validate=True)
        return list(struct.unpack(f"<{len(blob) // 2}e", blob))
    except Exception:  # noqa: BLE001 — a corrupt value is a cache miss
        return None


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


async def _keys(scope: str) -> tuple[str, str, str]:
    from app.core.cache import cache_version

    ver = await cache_version("semantic_cache")
    return (
        _VEC_KEY.format(ver=ver, scope=scope),
        _RESULT_KEY.format(ver=ver, scope=scope),
        _TS_KEY.format(ver=ver, scope=scope),
    )


def _scan_candidates(
    query_vec: list[float], stored: dict[str, str], threshold: float
) -> list[tuple[str, float]]:
    """Decode every stored vector and return the qualifying hits, best first.

    Pure CPU over up to ``semantic_cache_capacity`` vectors of ``embedding_dim``
    floats: the caller runs it on a worker thread so the scan never occupies the
    event loop. ``sorted`` is stable, so equal similarities keep the hash order
    they were read in.
    """
    candidates: list[tuple[str, float]] = []
    for qhash, payload in stored.items():
        cached_vec = _unpack_vector(payload)
        if cached_vec is None:
            continue
        sim = _cosine(query_vec, cached_vec)
        if sim >= threshold:
            candidates.append((qhash, sim))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


async def semantic_cache_get(
    query_vec: list[float], *, scope: str, threshold: float | None = None
) -> SemanticCacheHit | None:
    """Return a cached result if a similar query exceeds the similarity threshold.

    Linear scan over the stored query vectors of ``scope``. Returns ``None`` on
    miss, disabled, or any Redis error (best-effort, non-fatal).
    """
    from app.core.redis import async_value, get_redis

    s = _settings()
    if not getattr(s, "semantic_cache_enabled", False):
        return None
    thr = threshold if threshold is not None else getattr(s, "semantic_cache_threshold", 0.95)
    try:
        vkey, rkey, _tkey = await _keys(scope)
        r = await get_redis()
        all_vecs = await async_value(r.hgetall(vkey))
        if not all_vecs:
            return None
        candidates = await asyncio.to_thread(_scan_candidates, query_vec, all_vecs, thr)
        # Best-first: the first candidate that still has its result text wins, so
        # a stale/missing higher-similarity entry can't mask a valid lower one.
        for qhash, sim in candidates:
            result = await async_value(r.hget(rkey, qhash))
            if result:
                return SemanticCacheHit(result=result, similarity=sim, cached_query=qhash)
        return None
    except Exception:  # noqa: BLE001
        logger.debug("semantic cache get failed (non-fatal)", exc_info=True)
        return None


async def semantic_cache_put(query_vec: list[float], result: str, *, scope: str) -> None:
    """Store a query vector + result under ``scope`` for future similarity matches.

    Enforces LRU eviction at ``semantic_cache_capacity``. Best-effort, non-fatal.
    """
    from app.core.redis import get_redis

    s = _settings()
    if not getattr(s, "semantic_cache_enabled", False):
        return
    cap = getattr(s, "semantic_cache_capacity", 200)
    ttl = getattr(s, "semantic_cache_ttl_seconds", 1800)
    try:
        # The hash is over the vector to dedupe near-identical queries that would
        # otherwise bloat the ring; the similarity scan still uses the raw vector.
        qhash = sha256(json.dumps([round(v, 6) for v in query_vec]).encode()).hexdigest()[:32]
        payload = _pack_vector(query_vec)
        r = await get_redis()
        vkey, rkey, tkey = await _keys(scope)
        pipe = r.pipeline()
        pipe.hset(vkey, qhash, payload)
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
