"""Employee-scope persona/safety guard.

The bot serves TWO audiences: job candidates AND existing employees of
VFIC-managed projects (LG Display today, more coming). These guards pin that
employee/HR concerns (resignation, benefits, policy) are recognised as in-scope
in the persona and not bounced by the static safety fallbacks.

Regression for the misclassification where "tôi muốn nghỉ việc ở lg" was treated
as lạc đề (off-topic) because the persona was hard-scoped to job-finding only.
"""

from __future__ import annotations

from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.graph.safety import TECHNICAL_FALLBACK

_PERSONA = AGENT_SYSTEM_PROMPT.lower()
_FALLBACK = TECHNICAL_FALLBACK.lower()


def test_persona_names_existing_employees_as_audience():
    # Role/audience must cover both candidates and existing employees.
    assert "nhân viên" in _PERSONA or "đang làm" in _PERSONA, (
        "persona must name existing employees as an in-scope audience"
    )


def test_persona_does_not_reject_resignation_as_off_topic():
    # The off-topic rule used to say "chỉ trả lời về tìm việc" — which made any
    # employee concern (nghỉ việc, phúc lợi…) read as lạc đề. That exact phrase
    # must be gone, and resignation must be explicitly in-scope.
    assert "chỉ trả lời về tìm việc" not in _PERSONA, (
        "persona must not hard-restrict scope to job-finding only"
    )
    assert "nghỉ việc" in _PERSONA, (
        "persona must treat resignation as an in-scope employee concern"
    )


def test_technical_fallback_covers_employees_not_recruitment_only():
    # TECHNICAL_FALLBACK is emitted for genuine tech/code off-topic. It must not
    # narrow the bot to recruitment only — it must also name employee support so
    # an employee reading the fallback sees HR concerns as in scope.
    assert "nhân viên" in _FALLBACK, (
        f"TECHNICAL_FALLBACK must mention employee support: {TECHNICAL_FALLBACK!r}"
    )
