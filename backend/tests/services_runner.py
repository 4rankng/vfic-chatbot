"""In-process retrieval runner for the Vietnamese RAG gold gate.

Builds the fused + deduped + reranked candidate list for one case using the
**real** production code paths (``reciprocal_rank_fuse`` from
``app.services.retrieval.fusion`` and ``rerank_if_enabled`` from
``app.services.retrieval.reranker``) against fixture rows produced by
``tests.rag_gold.loader``.

This deliberately bypasses the Postgres HNSW path to keep CI fast, free, and
offline. The vector-arm cosine ranking is precomputed into the row dicts
during load (we know the query embedding and the chunk embeddings ahead of
time). The point of this runner is to exercise the **post-retrieval
pipeline** — exactly the code paths Phases 2–5 will modify.

Phase 4 will add ``dedup_by_sha256`` to this runner; Phase 2 will add
``mmr_dedup``. Both call into the same `merged` list between fusion and
rerank, mirroring the production wiring at
``backend/app/services/retrieval/repository.py:432-446``.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import get_settings
from app.services.retrieval.fusion import reciprocal_rank_fuse
from app.services.retrieval.reranker import rerank_if_enabled

from tests.rag_gold.loader import (
    GoldCase,
    GoldChunk,
    build_lexical_rows,
    build_vector_rows,
)


def build_rows_for_case(
    case: GoldCase,
    chunks: tuple[GoldChunk, ...],
    embeddings: dict[str, list[float]],
    *,
    top_k: int = 25,
    floor: float = 0.30,
) -> list[SimpleNamespace]:
    """Run the full post-retrieval pipeline for one case against fixtures.

    Steps mirror ``RetrievalRepository.match_documents`` exactly:
      1. Build vector arm rows (cosine sim from canned embeddings).
      2. Build lexical arm rows (term overlap on tokenized content).
      3. Short-circuit when both arms are empty.
      4. When only one arm has rows, rerank-only (mirrors production fallback).
      5. Otherwise fuse via RRF, then rerank.
    """
    vector_rows = build_vector_rows(case, chunks, embeddings, top_k=top_k, floor=floor)
    lexical_rows = build_lexical_rows(case, chunks, top_k=top_k)
    if not lexical_rows and not vector_rows:
        return []
    if not lexical_rows:
        return rerank_if_enabled(vector_rows, query_text=case.query)
    if not vector_rows:
        return rerank_if_enabled(lexical_rows, query_text=case.query)
    merged = reciprocal_rank_fuse(
        vector_rows,
        lexical_rows,
        top_k=top_k,
        rank_constant=get_settings().rag_rrf_rank_constant,
    )
    return rerank_if_enabled(merged, query_text=case.query)
