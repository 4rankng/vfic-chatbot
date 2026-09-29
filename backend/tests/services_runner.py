"""In-process retrieval runner for the Vietnamese RAG gold gate.

Builds the deduped + reranked candidate list for one case using the **real**
production code paths (``rerank_if_enabled`` from
``app.services.retrieval.reranker``) against fixture rows produced by
``tests.rag_gold.loader``.

This deliberately bypasses the Postgres HNSW path to keep CI fast, free, and
offline. The vector cosine ranking is precomputed into the row dicts during
load (we know the query embedding and the chunk embeddings ahead of time).
The point of this runner is to exercise the **post-retrieval pipeline**.

Production ``match_documents`` is vector-only since the lexical arm was
removed (a diacritic-folded substring collision ranked unrelated allowance
chunks above the relevant shift chunks); this runner mirrors that: vector
rows only, then rerank.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.retrieval.reranker import rerank_if_enabled
from tests.rag_gold.loader import (
    GoldCase,
    GoldChunk,
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
    """Run the post-retrieval pipeline for one case against fixtures.

    Steps mirror ``RetrievalRepository.match_documents`` exactly:
      1. Build vector rows (cosine sim from canned embeddings).
      2. Short-circuit when empty.
      3. Rerank.
    """
    vector_rows = build_vector_rows(case, chunks, embeddings, top_k=top_k, floor=floor)
    if not vector_rows:
        return []
    return list(rerank_if_enabled(vector_rows, query_text=case.query))
