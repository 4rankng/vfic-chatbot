"""Unit tests for the deterministic FAQ-bypass cascade (no DB / no LLM / no Redis).

Covers the pure gate logic (``build_exact_map`` / ``rerank`` / ``decide``) and the
``_FaqBypassAdapter`` composition (a fake repo + a fake cached-embed → hit / miss /
exception-abstain). Runner-level wiring (hit routes through the send tail, miss /
exception / None fall through) is pinned in ``test_graph_runner_turn.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.text import normalize_vietnamese_text as norm
from app.graph.ports import FaqBypassResult
from app.services.retrieval import faq_bypass as fb


def _row(
    *,
    id: str,
    answer: str = "Ans",
    similarity: float = 0.0,
    questions: list[str] | None = None,
    required_terms: list[str] | None = None,
    forbidden_terms: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        content=f"FAQ: q\n{answer}",
        source_quote=answer,
        summary=answer,
        questions=questions or [],
        required_terms=required_terms or [],
        forbidden_terms=forbidden_terms or [],
        similarity=similarity,
    )


# --- build_exact_map --------------------------------------------------------


def test_build_exact_map_indexes_normalized_variants():
    rows = [
        _row(id="1", questions=["Lương bao nhiêu?", "thu nhập thế nào"]),
        _row(id="2", questions=["Xe đưa đón không?"]),
    ]
    mapping = fb.build_exact_map(rows)
    assert mapping[norm("Lương bao nhiêu?")] == "1"
    assert mapping[norm("thu nhập thế nào")] == "1"
    assert mapping[norm("Xe đưa đón không?")] == "2"


def test_build_exact_map_first_variant_wins_on_collision():
    rows = [
        _row(id="1", questions=["câu giống nhau"]),
        _row(id="2", questions=["câu giống nhau"]),
    ]
    mapping = fb.build_exact_map(rows)
    assert mapping[norm("câu giống nhau")] == "1"


# --- rerank -----------------------------------------------------------------


def test_rerank_merges_by_id_and_weight_normalizes():
    vector_rows = [_row(id="1", similarity=0.9)]
    lexical_rows = [_row(id="1", similarity=0.7), _row(id="2", similarity=0.6)]
    scored = fb.rerank(vector_rows, lexical_rows)
    # id1 seen by both arms: (0.6*0.9 + 0.4*0.7) / 1.0 = 0.82
    assert scored[0].faq_id == "1"
    assert abs(scored[0].score - 0.82) < 1e-9
    assert scored[0].vec_sim == 0.9
    assert scored[0].tri_sim == 0.7
    # id2 seen by the lexical arm alone → scored by that arm only
    assert scored[1].faq_id == "2"
    assert scored[1].score == 0.6


def test_rerank_single_arm_candidate_scored_by_that_arm():
    scored = fb.rerank([_row(id="9", similarity=0.5)], [])
    assert len(scored) == 1
    assert scored[0].faq_id == "9"
    assert scored[0].score == 0.5


# --- decide -----------------------------------------------------------------


def _scored(faq_id: str, score: float, **kw) -> fb.Scored:
    return fb.Scored(
        faq_id=faq_id,
        answer=kw.get("answer", "A"),
        vec_sim=kw.get("vec_sim", score),
        tri_sim=kw.get("tri_sim", score),
        score=score,
        required_terms=kw.get("required_terms", []),
        forbidden_terms=kw.get("forbidden_terms", []),
    )


def test_decide_exact_match_accepts():
    query = "Lương bao nhiêu?"
    rows = [_row(id="1", questions=[query], similarity=0.9)]
    exact_map = fb.build_exact_map(rows)
    decision = fb.decide(query, exact_map, [_scored("1", 0.9)])
    assert decision.decision == fb.DECISION_ACCEPT
    assert decision.tier == fb.TIER_EXACT
    assert decision.scored is not None and decision.scored.faq_id == "1"


def test_decide_exact_blocked_by_forbidden_term():
    # An exact-variant match whose own rule terms reject it (here a forbidden
    # term that is a substring of the variant) abstains at the exact tier.
    query = "Lương cơ bản"
    rows = [_row(id="1", questions=[query], forbidden_terms=["bản"])]
    exact_map = fb.build_exact_map(rows)
    scored = [_scored("1", 1.0, forbidden_terms=["bản"])]
    decision = fb.decide(query, exact_map, scored)
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.tier == fb.TIER_EXACT
    assert decision.reason.startswith("exact_blocked:forbidden_present")


def test_decide_hybrid_accepts_when_score_and_margin_clear():
    # Query does not equal any variant → hybrid tier.
    scored = [_scored("1", 0.90), _scored("2", 0.70)]
    decision = fb.decide("muon hoi ve muc luong", {}, scored)
    assert decision.decision == fb.DECISION_ACCEPT
    assert decision.tier == fb.TIER_HYBRID


def test_decide_hybrid_rejects_below_floor():
    scored = [_scored("1", 0.60), _scored("2", 0.10)]
    decision = fb.decide("mot cau hoi", {}, scored)
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.reason.startswith("below_floor")


def test_decide_hybrid_rejects_on_margin():
    scored = [_scored("1", 0.90), _scored("2", 0.85)]  # margin 0.05 < 0.12
    decision = fb.decide("mot cau hoi", {}, scored)
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.reason.startswith("margin_fail")


def test_decide_hybrid_rejects_on_forbidden_term():
    scored = [_scored("1", 0.90, forbidden_terms=["phạt"]), _scored("2", 0.50)]
    decision = fb.decide("hỏi về lương và phạt", {}, scored)
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.reason.startswith("rule_blocked:forbidden_present")


def test_decide_hybrid_rejects_on_missing_required_term():
    scored = [
        _scored("1", 0.90, required_terms=["xe", "đưa đón"]),
        _scored("2", 0.50),
    ]
    decision = fb.decide("hỏi về xe chỉ", {}, scored)  # has "xe", missing "đưa đón"
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.reason.startswith("rule_blocked:required_missing")


def test_decide_abstains_with_no_candidates():
    decision = fb.decide("bất kỳ", {}, [])
    assert decision.decision == fb.DECISION_ABSTAIN
    assert decision.tier == fb.TIER_NONE
    assert decision.reason == "no_candidates"


# --- adapter (composition root glue) ----------------------------------------


class _FakeRepo:
    def __init__(self, vector_rows, lexical_rows, raise_on=None) -> None:
        self._v = vector_rows
        self._l = lexical_rows
        self._raise_on = raise_on

    async def match_faq(self, emb, top_k, floor):
        if self._raise_on == "vector":
            raise RuntimeError("boom")
        return self._v

    async def match_faq_lexical(self, query, top_k, threshold):
        if self._raise_on == "lexical":
            raise RuntimeError("boom")
        return self._l


@pytest.mark.asyncio
async def test_adapter_returns_result_on_confident_hit(monkeypatch):
    from app.graph.factories import _FaqBypassAdapter

    vector_rows = [_row(id="1", similarity=0.95, answer="Trả lời 1", questions=["luong"])]
    lexical_rows = [_row(id="1", similarity=0.8), _row(id="2", similarity=0.5)]
    monkeypatch.setattr("app.services.retrieval.RetrievalRepository", lambda db: _FakeRepo(vector_rows, lexical_rows))

    async def _fake_cached(embedder, query):
        return [0.1] * 8

    monkeypatch.setattr("app.graph.tools._cached_embed", _fake_cached)

    adapter = _FaqBypassAdapter(db=object(), embedder=object())
    result = await adapter.try_answer("muon hoi ve muc luong")
    assert isinstance(result, FaqBypassResult)
    assert result.answer == "Trả lời 1"
    assert result.faq_id == "1"


@pytest.mark.asyncio
async def test_adapter_abstains_on_low_score(monkeypatch):
    from app.graph.factories import _FaqBypassAdapter

    vector_rows = [_row(id="1", similarity=0.4)]  # below SCORE_FLOOR
    monkeypatch.setattr("app.services.retrieval.RetrievalRepository", lambda db: _FakeRepo(vector_rows, []))
    monkeypatch.setattr("app.graph.tools._cached_embed", lambda e, q: _async([0.1] * 8))

    adapter = _FaqBypassAdapter(db=object(), embedder=object())
    assert await adapter.try_answer("câu gì đó") is None


@pytest.mark.asyncio
async def test_adapter_abstains_when_retrieval_raises(monkeypatch):
    from app.graph.factories import _FaqBypassAdapter

    monkeypatch.setattr(
        "app.services.retrieval.RetrievalRepository",
        lambda db: _FakeRepo([], [], raise_on="vector"),
    )
    monkeypatch.setattr("app.graph.tools._cached_embed", lambda e, q: _async([0.1] * 8))

    adapter = _FaqBypassAdapter(db=object(), embedder=object())
    # Must never raise — abstain so the turn falls through to the agent.
    assert await adapter.try_answer("câu gì đó") is None


async def _async(value):
    return value
