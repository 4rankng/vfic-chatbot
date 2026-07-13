"""Golden set — the consolidated, labeled decision corpus for zero-LLM coverage.

Phase 1 of ``docs/chatbot-latency-improvement-plan.md`` calls for a golden set
that codifies, *before* any threshold tuning or coverage expansion, exactly
which candidate phrases must:

  * HIT the fast lane (greetings/thanks/goodbye/help — instant, no LLM);
  * FALL THROUGH the fast lane (factual questions, empty input, mixed intents);
  * ACCEPT the FAQ bypass (canonical questions, strong hybrid matches);
  * ABSTAIN from the FAQ bypass (below floor, margin fail, forbidden term,
    missing required term, no candidates);
  * NEVER reuse a global/template reply — personalized recommendation intents
    such as "tìm việc làm" depend on the lead profile, project, and current job
    state, so they must reach the agent even if they look factual.

This file is the structure the plan references. It is authorable from domain
knowledge (not production traffic) and doubles as the regression net that
catches future fast-lane / FAQ-bypass regressions. Each case is labeled with its
expected lane and decision so a failure pinpoints the exact contract that broke.

Companion files:
  * ``test_fast_lane.py``  — the fast-lane unit tests (route table + persona voice)
  * ``test_faq_bypass.py`` — the FAQ-bypass gate-logic unit tests (rerank/decide)
This file consolidates the *decision taxonomy* across both, adding the
personalized-must-reach-agent cases that span both lanes.
"""

from __future__ import annotations

import pytest

from app.graph.fast_lane import match as fast_lane_match
from app.services.retrieval import faq_bypass as fb

# ---------------------------------------------------------------------------
# Fast-lane golden cases
# ---------------------------------------------------------------------------

FAST_LANE_HIT = [
    # (phrase, intent) — must route to a canned template, never the agent
    ("hi", "greeting"),
    ("Chào bạn!", "greeting"),
    ("XIN CHÀO", "greeting"),
    ("cảm ơn bạn nhe", "thanks"),
    ("thanks ban", "thanks"),
    ("tạm biệt", "goodbye"),
    ("bye bye", "goodbye"),
    ("bạn giúp gì được", "help"),
    ("bạn là ai", "help"),
]


FAST_LANE_FALLTHROUGH = [
    # Factual questions — answers live in the KB, must reach RAG + agent.
    "lương bao nhiêu",
    "có xe đưa đón không",
    "địa điểm làm việc ở đâu",
    "số điện thoại liên hệ",
    "hồ sơ cần chuẩn bị gì",
    # Empty / punctuation-only — no fake answer.
    "",
    "????",
    "!!!",
    # Mixed intent — a greeting carrying a real question must NOT be templated.
    "chào bạn, lương bao nhiêu?",
    "hi, có xe đưa đón không?",
]


# ---------------------------------------------------------------------------
# FAQ-bypass golden cases (pure decide() inputs — no DB/Redis)
# ---------------------------------------------------------------------------


def _scored(
    faq_id: str, score: float, *, answer: str = "A", **kw
) -> fb.Scored:
    return fb.Scored(
        faq_id=faq_id,
        answer=answer,
        vec_sim=kw.get("vec_sim", score),
        tri_sim=kw.get("tri_sim", score),
        score=score,
        required_terms=kw.get("required_terms", []),
        forbidden_terms=kw.get("forbidden_terms", []),
    )


FAQ_ACCEPT_CASES = [
    # (label, query, exact_map, scored_list, expected_tier)
    (
        "exact_match",
        "Lương bao nhiêu?",
        {},
        [],
        fb.TIER_EXACT,  # populated below — see fixture note
    ),
    (
        "hybrid_strong_clear_margin",
        "muon hoi ve muc luong",
        {},
        [_scored("1", 0.90), _scored("2", 0.60)],
        fb.TIER_HYBRID,
    ),
]


FAQ_ABSTAIN_CASES = [
    # (label, query, scored_list, reason_prefix)
    ("below_floor", "mot cau hoi", [_scored("1", 0.50)], "below_floor"),
    ("margin_fail", "mot cau hoi", [_scored("1", 0.90), _scored("2", 0.85)], "margin_fail"),
    (
        "forbidden_term_present",
        "hỏi về lương và phạt",
        [_scored("1", 0.90, forbidden_terms=["phạt"]), _scored("2", 0.50)],
        "rule_blocked:forbidden_present",
    ),
    (
        "required_term_missing",
        "hỏi về xe chỉ",
        [_scored("1", 0.90, required_terms=["xe", "đưa đón"]), _scored("2", 0.50)],
        "rule_blocked:required_missing",
    ),
    ("no_candidates", "bất kỳ", [], "no_candidates"),
]


# ---------------------------------------------------------------------------
# Personalized-must-reach-agent cases
# ---------------------------------------------------------------------------

PERSONALIZED_MUST_REACH_AGENT = [
    # These intents depend on the lead profile, conversation history, project
    # state, and active jobs — a global/template reply would be wrong. The fast
    # lane must NOT match them (verified below), and the FAQ bypass would only
    # fire if a canonical FAQ existed for the *exact* phrasing, which is safe
    # because canonical answers are admin-authored and content-scoped.
    "tìm việc làm",
    "gợi ý việc cho mình",
    "có việc nào phù hợp không",
    "việc nào hợp với hồ sơ em",
    "tìm công việc gần nhà",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("phrase", "intent"), FAST_LANE_HIT)
def test_golden_fast_lane_hits(phrase, intent):
    """Non-factual greetings/thanks/goodbye/help MUST route to a canned template."""
    hit = fast_lane_match(phrase)
    assert hit is not None, f"expected fast-lane HIT for {phrase!r}"
    assert hit.intent == intent


@pytest.mark.parametrize("phrase", FAST_LANE_FALLTHROUGH)
def test_golden_fast_lane_falls_through(phrase):
    """Factual, empty, and mixed-intent phrases MUST fall through to RAG + agent."""
    assert fast_lane_match(phrase) is None, (
        f"fast lane wrongly swallowed {phrase!r} — factual/empty/mixed input "
        "must reach the agent, not a template"
    )


@pytest.mark.parametrize("phrase", PERSONALIZED_MUST_REACH_AGENT)
def test_golden_personalized_never_uses_template(phrase):
    """Personalized recommendation intents MUST NOT match the fast lane.

    ``tìm việc làm`` and friends depend on the candidate's profile and active
    jobs — they can never reuse a global reply (latency plan, explicit non-goal:
    'generic final-answer semantic cache').
    """
    assert fast_lane_match(phrase) is None, (
        f"fast lane matched {phrase!r} — personalized recommendation intents "
        "must reach the agent"
    )


def test_golden_faq_exact_accepts():
    """A normalized exact-variant match accepts at the exact tier."""
    from types import SimpleNamespace

    from app.core.text import normalize_vietnamese_text as norm

    query = "Lương bao nhiêu?"
    rows = [
        SimpleNamespace(
            id="1",
            questions=[query],
            required_terms=[],
            forbidden_terms=[],
        )
    ]
    exact_map = fb.build_exact_map(rows)
    decision = fb.decide(query, exact_map, [_scored("1", 0.9)])
    assert decision.decision == fb.DECISION_ACCEPT
    assert decision.tier == fb.TIER_EXACT
    # The exact map key is the normalized query — verify normalization is stable.
    assert norm(query) in exact_map


@pytest.mark.parametrize(("label", "query", "scored", "reason_prefix"), FAQ_ABSTAIN_CASES)
def test_golden_faq_abstains(label, query, scored, reason_prefix):
    """Each abstention reason must fire on its canonical input shape."""
    decision = fb.decide(query, {}, scored)
    assert decision.decision == fb.DECISION_ABSTAIN, (
        f"{label}: expected ABSTAIN, got {decision.decision} ({decision.reason})"
    )
    assert decision.reason.startswith(reason_prefix), (
        f"{label}: expected reason prefix {reason_prefix!r}, got {decision.reason!r}"
    )
