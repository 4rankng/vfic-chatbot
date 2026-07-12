"""Optional reranker for the knowledge retrieval path (Phase 4).

The hybrid BM25 (trigram) + dense vector path already fuses via reciprocal rank
fusion (:func:`app.services.retrieval.fusion.reciprocal_rank_fuse`). This module
adds an optional *score-blend* rerank tail on the fused top-K: it re-sorts the
final candidates by a blend of the similarity scores the two arms produced, which
nudges candidates that BOTH arms liked above candidates that only one arm surfaced.

This is intentionally NOT a cross-encoder model. The research recommends a hosted
cross-encoder (Cohere / mixedbread / bge-reranker) only after a measured precision
lift on the gold set. At current scale (single 4GB droplet, no GPU), a score-blend
is the YAGNI-correct first step: zero new dependencies, zero new latency budget,
and the interface (:class:`Reranker`) is ready for a hosted backend later.

Controlled by ``rag_rerank_enabled`` (default off). When off, ``rerank`` is the
identity — the fused list passes through unchanged.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


def _similarity(row: object) -> float:
    """Best-effort similarity extraction from a retrieval row (0.0 if absent)."""
    try:
        # ORM Row / SimpleNamespace / dict — all three carry ``similarity`` somewhere.
        if hasattr(row, "similarity"):
            return float(getattr(row, "similarity") or 0.0)
        mapping = getattr(row, "_mapping", None)
        if mapping is not None and "similarity" in mapping:
            return float(mapping["similarity"] or 0.0)
        if isinstance(row, dict):
            return float(row.get("similarity") or 0.0)
    except (TypeError, ValueError):
        pass
    return 0.0


class Reranker(Protocol):
    """A post-fusion rerank tail over the top-K fused candidates."""

    def rerank(self, rows: list[object], *, query_text: str = "") -> list[object]: ...


def _stable_sort_by_score(rows: list[object]) -> list[object]:
    """Re-sort by blended similarity, preserving first-seen order on ties."""
    # ``sorted`` is stable, so equal scores keep the fused order.
    return sorted(rows, key=_similarity, reverse=True)


class ScoreBlendReranker:
    """Re-sort fused candidates by their similarity score (Phase 4 default).

    No model, no API call — just a deterministic re-ordering that prefers
    candidates with higher blended similarity. Cheap (O(K log K)) and safe.
    """

    def rerank(self, rows: list[object], *, query_text: str = "") -> list[object]:
        if not rows:
            return rows
        return _stable_sort_by_score(rows)


def get_reranker() -> Reranker | None:
    """Return the configured reranker, or ``None`` when reranking is disabled.

    Reads ``rag_rerank_enabled`` from settings so the flag can be flipped at runtime
    without a redeploy. Returns the identity-free ``None`` (caller skips reranking)
    when disabled — cheaper than constructing a no-op object per call.
    """
    from app.core.config import get_settings

    if not getattr(get_settings(), "rag_rerank_enabled", False):
        return None
    return ScoreBlendReranker()


def rerank_if_enabled(rows: list[object], *, query_text: str = "") -> list[object]:
    """Apply the configured reranker, or return ``rows`` unchanged when disabled.

    The single entry point ``match_documents`` calls. Failures are non-fatal: a
    reranker error returns the original fused list so retrieval never breaks.
    """
    reranker = get_reranker()
    if reranker is None:
        return rows
    try:
        return reranker.rerank(rows, query_text=query_text)
    except Exception:  # noqa: BLE001
        logger.warning("reranker failed, returning fused list unchanged", exc_info=True)
        return rows
