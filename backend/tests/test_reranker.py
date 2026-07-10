"""Tests for the optional knowledge-path reranker (Phase 4).

The reranker is a post-fusion tail on ``match_documents``. When disabled (default)
the fused list passes through unchanged; when enabled it re-sorts by blended
similarity. Pure-Python: no DB, no model API.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.retrieval import reranker as reranker_mod
from app.services.retrieval.reranker import ScoreBlendReranker, rerank_if_enabled


def _row(id: str, similarity: float):
    """A retrieval row with a similarity attribute (mirrors the real Row shape)."""
    return SimpleNamespace(id=id, similarity=similarity, content="x")


# --- ScoreBlendReranker ------------------------------------------------------


def test_score_blend_reranks_by_similarity_desc():
    rows = [_row("low", 0.31), _row("high", 0.92), _row("mid", 0.55)]
    out = ScoreBlendReranker().rerank(rows)
    assert [r.id for r in out] == ["high", "mid", "low"]


def test_score_blend_preserves_order_on_ties():
    """Equal scores keep the fused first-seen order (stable sort)."""
    rows = [_row("a", 0.5), _row("b", 0.5), _row("c", 0.5)]
    out = ScoreBlendReranker().rerank(rows)
    assert [r.id for r in out] == ["a", "b", "c"]


def test_score_blend_empty_returns_empty():
    assert ScoreBlendReranker().rerank([]) == []


def test_score_blend_handles_missing_similarity_as_zero():
    """A row with no similarity attribute sorts last, not crashes."""
    rows = [
        SimpleNamespace(id="no_sim", content="x"),  # no similarity attr
        _row("has_sim", 0.4),
    ]
    out = ScoreBlendReranker().rerank(rows)
    assert [r.id for r in out] == ["has_sim", "no_sim"]


def test_score_blend_handles_dict_rows():
    """Dict-shaped rows (as returned in some test paths) work too."""
    rows = [{"id": "a", "similarity": 0.1}, {"id": "b", "similarity": 0.9}]
    out = ScoreBlendReranker().rerank(rows)
    assert [r["id"] for r in out] == ["b", "a"]


# --- rerank_if_enabled (flag gating) -----------------------------------------


def test_rerank_disabled_returns_input_unchanged(monkeypatch):
    """Default: rag_rerank_enabled=False → identity passthrough."""
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(rag_rerank_enabled=False))
    rows = [_row("low", 0.1), _row("high", 0.9)]
    out = rerank_if_enabled(rows)
    assert out is rows  # same object — no copy, no rerank


def test_rerank_enabled_reorders(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(rag_rerank_enabled=True))
    rows = [_row("low", 0.1), _row("high", 0.9)]
    out = rerank_if_enabled(rows)
    assert [r.id for r in out] == ["high", "low"]


def test_rerank_failure_falls_back_to_input(monkeypatch):
    """A reranker error must never break retrieval — returns the original list."""
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(rag_rerank_enabled=True))

    class _Boom:
        def rerank(self, rows, *, query_text=""):
            raise RuntimeError("model down")

    monkeypatch.setattr(reranker_mod, "get_reranker", lambda: _Boom())
    rows = [_row("a", 0.1)]
    out = rerank_if_enabled(rows)
    assert out is rows  # unchanged despite the crash
