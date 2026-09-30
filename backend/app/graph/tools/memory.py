"""Memory tool: recall of remembered facts about the current candidate.

All SQL lives in ``app.services.retrieval.RetrievalRepository`` (behind the
``GraphRetrievalPort``); this module owns the embedding + Vietnamese formatting
only.
"""

from __future__ import annotations

import json
import logging

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.config import get_settings
from app.core.vector import vec_literal
from app.graph.embed_cache import cached_embed
from app.graph.llm import Embedder
from app.graph.ports import GraphRetrievalPort
from app.graph.tools._shared import _cache_digest

logger = logging.getLogger(__name__)


_PRIVATE_MEMORY_NOTICE = (
    "NGỮ CẢNH RIÊNG TƯ — chỉ dùng các dữ kiện dưới đây để hiểu ngữ cảnh hoặc tránh hỏi "
    "lặp. Không được trích dẫn, tóm tắt hoặc nói rằng bạn biết/đã nhớ các dữ kiện này "
    "trong câu trả lời gửi cho người dùng."
)


async def search_user_memory(
    retrieval: GraphRetrievalPort,
    embedder: Embedder,
    chat_id: str,
    query: str,
    top_k: int = 5,
) -> str:
    s = get_settings()
    memory_version = await cache_version(f"memory:{chat_id}") if s.rag_cache_enabled else "0"
    # v2 prevents a pre-privacy-notice result from being reused during the
    # normal RAG cache TTL after this response-boundary change.
    cache_key = f"rag:memory:v2:{_cache_digest(chat_id, query, top_k, memory_version)}"
    if s.rag_cache_enabled:
        cached = await cache_get_json(cache_key)
        if isinstance(cached, str):
            return cached
    emb = vec_literal(await cached_embed(embedder, query))
    rows = await retrieval.match_memories(emb, top_k, json.dumps({"chat_id": chat_id}))
    if not rows:
        result = "Không có thông tin ghi nhớ về người dùng này."
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
        return result
    logger.debug("search_user_memory: %d rows for chat %s", len(rows), chat_id)
    result = _PRIVATE_MEMORY_NOTICE + "\n" + "\n".join(
        f"- {r.content} (sim={r.similarity:.2f})" for r in rows
    )
    if s.rag_cache_enabled:
        await cache_set_json(cache_key, result, s.rag_result_cache_ttl_seconds)
    return result
