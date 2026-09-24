"""Private cross-domain helpers shared by the graph tool modules.

Kept out of ``__init__`` (the import-path contract surface) so tool modules can
import them without cycles; nothing outside ``app.graph.tools`` may rely on
this module.
"""

from __future__ import annotations

import base64
import json
import struct
from hashlib import sha256

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.graph.cache_key import normalize_query
from app.graph.llm import Embedder


def _cache_digest(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _pack_vector(vector: list[float]) -> str:
    """Pack an embedding as base64 float16 (~2 bytes/dim vs ~20 as a JSON array)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def _unpack_vector(payload: object) -> list[float] | None:
    """Inverse of :func:`_pack_vector`.

    Returns None on any non-packed payload: legacy JSON-array entries written
    before the packed format simply miss and repopulate on the next embed.
    """
    if not isinstance(payload, str):
        return None
    try:
        blob = base64.b64decode(payload, validate=True)
        return list(struct.unpack(f"<{len(blob) // 2}e", blob))
    except Exception:  # noqa: BLE001 — corrupt/legacy values are a cache miss
        return None


async def _cached_embed(embedder: Embedder, query: str) -> list[float]:
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
    vector = _unpack_vector(await cache_get_json(key))
    if vector:
        return vector
    vector = await embedder(query)
    try:
        payload = _pack_vector(vector)
    except Exception:  # noqa: BLE001 — an unrepresentable vector must not fail the turn
        return vector
    await cache_set_json(key, payload, s.embedding_cache_ttl_seconds)
    return vector


def _single_line(value: object, *, limit: int = 180) -> str:
    """Bound one scalar before including it in untrusted tool data."""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{clipped or text[: limit - 1]}…"
