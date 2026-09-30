"""Cached query embedding (shared by the retrieval tools and the answer cache).

Every retrieval path embeds the user's query once and then reads it back from a
version-free content-addressed key, so a repeated question costs no embedding
API call. The key hashes the *normalized* query, so case/Unicode-form/whitespace
variants share one entry; the embedder itself still receives the raw query.
"""

from __future__ import annotations

from hashlib import sha256

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.vector import pack_vector, unpack_vector
from app.graph.cache_key import normalize_query
from app.graph.llm import Embedder


async def cached_embed(embedder: Embedder, query: str) -> list[float]:
    """Embed ``query``, reusing the Redis entry when the normalized form matches."""
    s = get_settings()
    if not s.rag_cache_enabled:
        return await embedder(query)
    # Hash the normalised query (same normalisation as the answer cache) so
    # case/Unicode-form/whitespace variants share one key; the embedder still
    # receives the original raw query.
    normalized = normalize_query(query)
    query_hash = sha256(normalized.encode("utf-8")).hexdigest()
    provider = (s.embedding_provider or "openrouter").strip().lower()
    model = s.openrouter_embedding_model if provider == "openrouter" else s.gemini_embedding_model
    key = f"embed:{provider}:{model}:{s.embedding_dim}:{query_hash}"
    vector = unpack_vector(await cache_get_json(key))
    if vector:
        return vector
    vector = await embedder(query)
    try:
        payload = pack_vector(vector)
    except Exception:  # noqa: BLE001 — an unrepresentable vector must not fail the turn
        return vector
    await cache_set_json(key, payload, s.embedding_cache_ttl_seconds)
    return vector
