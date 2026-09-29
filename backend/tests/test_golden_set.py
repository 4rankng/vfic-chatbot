"""Golden set — the consolidated, labeled decision corpus for the routing lanes.

The corpus codifies, *before* any threshold tuning or coverage expansion,
exactly which candidate phrases must:

  * be judged a pure pleasantry by the Jev fan-out (greetings/thanks/goodbye
    — the small_talk intent);
  * NOT be judged a pure pleasantry (factual, empty, or mixed-intent input);
  * NEVER be templated — personalized recommendation intents such as
    "tìm việc làm" depend on the lead profile, project, and current job
    state, so they must reach the agent with that context.

The template fast lane these cases once pinned was removed: every message
reaches the LLM so the reply can use the current project context and
conversation history. The message-level corpus doubles as the expectation
table for the opt-in live replay (``JEV_EVAL=1``) — the shadow-mode seed for
gating automation on measured agreement.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Pleasantry golden cases
# ---------------------------------------------------------------------------

# Phrases the Jev fan-out must judge a pure pleasantry (small_talk intent).
PLEASANTRY_HIT = [
    "hi",
    "Chào bạn!",
    "XIN CHÀO",
    "cảm ơn bạn nhe",
    "thanks ban",
    "tạm biệt",
    "bye bye",
]

# Help/meta questions ("bạn là ai", "bạn giúp gì được") were keyword-matched to
# the canned menu under the old fast lane. Jev judges them substantive and
# routes them to the agent, which answers from the persona — the better
# outcome. Kept here as help-adjacent corpus with agent-path expectations.
PLEASANTRY_HELP_AGENT_OK = [
    "bạn giúp gì được",
    "bạn là ai",
]

# Factual, empty, and mixed-intent phrases — must reach RAG + agent.
PLEASANTRY_FALLTHROUGH = [
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

# Expectation table for the opt-in live replay: (phrase, expect_pleasantry).
# Empty and punctuation-only inputs are policy-level (no model call needed),
# so they are excluded here.
_JEV_EVAL_EMPTY_OR_PUNCTUATION = {"", "????", "!!!"}
JEV_EVAL_EXPECTATIONS = (
    [(phrase, True) for phrase in PLEASANTRY_HIT]
    + [
        (phrase, False)
        for phrase in PLEASANTRY_FALLTHROUGH
        if phrase not in _JEV_EVAL_EMPTY_OR_PUNCTUATION
    ]
    + [(phrase, False) for phrase in PLEASANTRY_HELP_AGENT_OK]
    + [(phrase, False) for phrase in PERSONALIZED_MUST_REACH_AGENT]
)


# ---------------------------------------------------------------------------
# Opt-in live replay — the shadow-mode seed (no network by default)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("JEV_EVAL") != "1" or not os.environ.get("JEV_API_KEY"),
    reason="opt-in live Jev replay: set JEV_EVAL=1 + JEV_API_KEY",
)
@pytest.mark.parametrize(("phrase", "expect_pleasantry"), JEV_EVAL_EXPECTATIONS)
async def test_live_jev_golden_replay(phrase, expect_pleasantry) -> None:
    """Replay the golden corpus against the real Jev API.

    Run with ``JEV_EVAL=1`` to measure agreement before trusting automation.
    """
    from app.graph.decisions import JevDecisionClient

    client = JevDecisionClient(api_key=os.environ["JEV_API_KEY"])
    decisions = await client.decide_turn(user_text=phrase, recent_messages=[])
    assert decisions.pleasantry == expect_pleasantry, (
        f"{phrase!r}: expected pleasantry={expect_pleasantry}, got {decisions.pleasantry}"
    )
