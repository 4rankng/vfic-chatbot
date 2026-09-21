"""Private cross-domain helpers shared by the graph tool modules.

Kept out of ``__init__`` (the import-path contract surface) so tool modules can
import them without cycles; nothing outside ``app.graph.tools`` may rely on
this module.
"""

from __future__ import annotations

import json
from hashlib import sha256

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.graph.llm import Embedder


def _cache_digest(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


async def _cached_embed(embedder: Embedder, query: str) -> list[float]:
    s = get_settings()
    if not s.rag_cache_enabled:
        return await embedder(query)
    query_hash = sha256(query.encode("utf-8")).hexdigest()
    provider = (s.embedding_provider or "openrouter").strip().lower()
    model = s.openrouter_embedding_model if provider == "openrouter" else s.gemini_embedding_model
    key = f"embed:{provider}:{model}:{s.embedding_dim}:{query_hash}"
    cached = await cache_get_json(key)
    if isinstance(cached, list) and cached:
        return [float(v) for v in cached]
    vector = await embedder(query)
    await cache_set_json(key, vector, s.embedding_cache_ttl_seconds)
    return vector


def _single_line(value: object, *, limit: int = 180) -> str:
    """Bound one scalar before including it in untrusted tool data."""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{clipped or text[: limit - 1]}…"
