"""Golden set — the consolidated, labeled decision corpus for the routing lanes.

Phase 1 of ``docs/chatbot-latency-improvement-plan.md`` calls for a golden set
that codifies, *before* any threshold tuning or coverage expansion, exactly
which candidate phrases must:

  * HIT the template lane (greetings/thanks/goodbye/help — instant, no LLM);
  * FALL THROUGH the template lane (factual, empty, or mixed-intent input);
  * NEVER reuse a global/template reply — personalized recommendation intents
    such as "tìm việc làm" depend on the lead profile, project, and current job
    state, so they must reach the agent.

Since the keyword router was replaced by the Jev fan-out, the message-level
corpus doubles as the expectation table for the opt-in live replay
(``JEV_EVAL=1``) — the shadow-mode seed for gating automation on measured
agreement. The FAQ-bypass gates remain pure-unit (no DB/Redis).
"""

from __future__ import annotations

import os

import pytest

from app.graph.fast_lane import template_for
from app.services.retrieval import faq_bypass as fb

# ---------------------------------------------------------------------------
# Template-lane golden cases
# ---------------------------------------------------------------------------

# (phrase, pleasantry kind) — must route to a canned template, never the agent.
FAST_LANE_HIT = [
    ("hi", "greeting"),
    ("Chào bạn!", "greeting"),
    ("XIN CHÀO", "greeting"),
    ("cảm ơn bạn nhe", "thanks"),
    ("thanks ban", "thanks"),
    ("tạm biệt", "goodbye"),
    ("bye bye", "goodbye"),
]

# Help/meta questions ("bạn là ai", "bạn giúp gì được") were keyword-matched to
# the canned menu under the old fast lane. Jev judges them substantive and
# routes them to the agent, which answers from the persona — the better
# outcome. Kept here as help-adjacent corpus with agent-path expectations.
FAST_LANE_HELP_AGENT_OK = [
    "bạn giúp gì được",
    "bạn là ai",
]

# Factual, empty, and mixed-intent phrases — must reach RAG + agent.
FAST_LANE_FALLTHROUGH = [
    "lương bao nhiêu",
    "có xe đưa đón không",
    "địa điểm làm việc ở đâu",
    "số điện thoại liên hệ",
    "hồ sơ cần chuẩn bị gì",
    "",
    "????",
    "!!!",
    "chào bạn, lương bao nhiêu?",
    "hi, có xe đưa đón không?",
]

# These depend on lead profile, conversation history, project state, and
# active jobs — a global/template reply would be wrong.
PERSONALIZED_MUST_REACH_AGENT = [
    "tìm việc làm",
    "gợi ý việc cho mình",
    "có việc nào phù hợp không",
    "việc nào hợp với hồ sơ em",
    "tìm công việc gần nhà",
]

# Expectation table for the opt-in live replay: (phrase, pleasantry, kind).
# Empty and punctuation-only inputs are policy-level (no model call needed),
# so they are excluded here.
_JEV_EVAL_EMPTY_OR_PUNCTUATION = {"", "????", "!!!"}
JEV_EVAL_EXPECTATIONS = (
    [(phrase, True, kind) for phrase, kind in FAST_LANE_HIT]
    + [
        (phrase, False, "none")
        for phrase in FAST_LANE_FALLTHROUGH
        if phrase not in _JEV_EVAL_EMPTY_OR_PUNCTUATION
    ]
    + [(phrase, False, "none") for phrase in FAST_LANE_HELP_AGENT_OK]
    + [(phrase, False, "none") for phrase in PERSONALIZED_MUST_REACH_AGENT]
)


# ---------------------------------------------------------------------------
# Template-lane pins (pure unit)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("phrase", "kind"), FAST_LANE_HIT)
def test_template_lane_kinds_are_templatable(phrase: str, kind: str) -> None:
    """Every corpus kind maps to a real template with the neutral persona voice."""
    hit = template_for(kind)
    assert hit is not None, f"no template for corpus kind {kind!r} ({phrase!r})"
    assert hit.intent == kind
    assert "anh/chị" in hit.reply


@pytest.mark.parametrize("phrase", PERSONALIZED_MUST_REACH_AGENT)
def test_golden_personalized_never_uses_template(phrase: str) -> None:
    """Personalized intents must not be judged pleasantry by the eval table."""
    for candidate, pleasantry, _kind in JEV_EVAL_EXPECTATIONS:
        if candidate == phrase:
            assert pleasantry is False


# ---------------------------------------------------------------------------
# FAQ-bypass golden cases (pure decide() inputs — no DB/Redis)
# ---------------------------------------------------------------------------


def _scored(
    faq_id: str,
    score: float,
    *,
    answer: str = "A",
    **kw,
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


def test_golden_faq_exact_accepts() -> None:
    """A normalized exact-variant match accepts at the exact tier."""
    from types import SimpleNamespace

    from app.shared.domain.text import normalize_vietnamese_text as norm

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
    assert norm(query) in exact_map


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


# ---------------------------------------------------------------------------
# Opt-in live replay — the shadow-mode seed (no network by default)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("JEV_EVAL") != "1" or not os.environ.get("JEV_API_KEY"),
    reason="opt-in live Jev replay: set JEV_EVAL=1 + JEV_API_KEY",
)
@pytest.mark.parametrize(("phrase", "expect_pleasantry", "expect_kind"), JEV_EVAL_EXPECTATIONS)
async def test_live_jev_golden_replay(phrase, expect_pleasantry, expect_kind) -> None:
    """Replay the golden corpus against the real Jev API.

    Run with ``JEV_EVAL=1`` to measure agreement before trusting automation.
    """
    from app.graph.decisions import JevDecisionClient

    client = JevDecisionClient(api_key=os.environ["JEV_API_KEY"])
    decisions = await client.decide_turn(user_text=phrase, recent_messages=[])
    assert decisions.pleasantry == expect_pleasantry, (
        f"{phrase!r}: expected pleasantry={expect_pleasantry}, got "
        f"{decisions.pleasantry} (kind={decisions.pleasantry_kind})"
    )
    if expect_pleasantry:
        assert decisions.pleasantry_kind == expect_kind
