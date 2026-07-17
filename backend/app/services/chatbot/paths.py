"""Four bounded turn paths (Tech-Lead Directive §2).

Path A — structured-data fast path (SQL tool + formatter, zero LLM)
Path B — curated FAQ path (FAQ lookup, zero LLM)
Path C — grounded retrieval path (hybrid search + ONE LLM call)
Path D — ambiguous clarification (ONE template clarification)

Each path is a standalone orchestrator returning a ``PathOutcome`` that the
runner (C-1) flows into the existing grounding + ownership + outbox pipeline.

The router (Phase 12) dispatches to one of these based on intent. Today the
runner.py inline branching handles fast_lane / faq_bypass / agent; this module
formalizes that into named paths so the dispatch is testable in isolation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.chatbot.budget import BudgetExhausted, CallKind, TurnBudget

logger = logging.getLogger(__name__)

# Volatile operational claims normally bypass the static FAQ path. A caller that
# has already established a specific published recruitment-evidence context may
# opt in to returning the exact curated FAQ instead. Generic job listings must
# still take the structured catalog path before reaching this function.
_VOLATILE_FACT_MARKERS = (
    "lương",
    "thu nhập",
    "ca làm",
    "giờ làm",
    "tăng ca",
    "phụ cấp",
    "xe đưa đón",
    "tuyến xe",
    "xe lúc",
    "xe mấy",
    "đón xe",
    "số điện thoại",
    "hotline",
    "liên hệ",
    "đang tuyển",
    "còn tuyển",
    "còn vị trí",
)


@dataclass(frozen=True)
class PathOutcome:
    """The result of one bounded path.

    ``reply`` is the candidate text (pre-safety). ``cannot_handle`` signals the
    runner to fall back to Path C (the agent) — e.g. Path A's tool returned
    not-found. ``outcome_label`` is the SLO lane tag.
    """

    reply: str
    outcome_label: str
    cannot_handle: bool = False
    metadata: dict = None  # type: ignore[assignment]


# ─── Path A: structured-data fast path ───────────────────────────────────────


async def path_a_structured(
    *,
    intent: str,
    entities: dict,
    db,
    budget: TurnBudget,
) -> PathOutcome:
    """Directive §2 Path A: SQL tool + deterministic formatter, zero LLM calls.

    ``intent`` is one of: bus_schedule_lookup, benefit_lookup,
    working_hours_lookup, requirement_lookup, job_lookup. ``entities`` is the
    router-extracted dict (origin, requested_time, job_id, etc.).
    """
    # Path A makes ZERO routing/generation calls — only a DB read.
    # Asserting the budget is unnecessary (no LLM/embed/rerank consumed), but
    # document the invariant for future readers.
    from app.services.knowledge.tools.domain_tools import (
        format_benefits,
        format_working_hours,
        format_job_requirements,
        get_benefits,
        get_working_hours,
        get_job_requirements,
    )

    if intent == "benefit_lookup":
        result = await get_benefits(
            db,
            job_id=entities.get("job_id"),
            active_kb_version_id=entities.get("active_kb_version_id"),
        )
        if not result.found:
            return PathOutcome(reply="", outcome_label="structured_miss", cannot_handle=True)
        return PathOutcome(reply=format_benefits(result), outcome_label="structured")
    if intent == "working_hours_lookup":
        result = await get_working_hours(
            db,
            job_id=entities.get("job_id"),
            active_kb_version_id=entities.get("active_kb_version_id"),
        )
        if not result.found:
            return PathOutcome(reply="", outcome_label="structured_miss", cannot_handle=True)
        return PathOutcome(reply=format_working_hours(result), outcome_label="structured")
    if intent == "requirement_lookup":
        if not entities.get("job_id"):
            return PathOutcome(reply="", outcome_label="structured_miss", cannot_handle=True)
        result = await get_job_requirements(
            db,
            job_id=entities["job_id"],
            active_kb_version_id=entities.get("active_kb_version_id"),
        )
        if not result.found:
            return PathOutcome(reply="", outcome_label="structured_miss", cannot_handle=True)
        return PathOutcome(reply=format_job_requirements(result), outcome_label="structured")
    # Unsupported intent for Path A → signal cannot_handle so runner falls back.
    return PathOutcome(reply="", outcome_label="structured_miss", cannot_handle=True)


# ─── Path B: curated FAQ path ────────────────────────────────────────────────


async def path_b_faq(
    *,
    user_text: str,
    normalized_question: str,
    db,
    budget: TurnBudget,
    active_kb_version_id: str | None = None,
    published_vacancy_evidence: bool = False,
) -> PathOutcome:
    """Directive §2 Path B: FAQ lookup, zero LLM calls.

    Exact normalized-question match → stored answer. Dynamic FAQs (resolution_type='tool')
    signal cannot_handle so the runner routes to Path A's tool instead.
    """
    if (
        any(marker in user_text.casefold() for marker in _VOLATILE_FACT_MARKERS)
        and not published_vacancy_evidence
    ):
        return PathOutcome(reply="", outcome_label="faq_volatile", cannot_handle=True)

    from app.services.knowledge.tools.domain_tools import format_faq, get_faq_entry

    result = await get_faq_entry(
        db,
        normalized_question=normalized_question,
        active_kb_version_id=active_kb_version_id,
    )
    if not result.found:
        return PathOutcome(reply="", outcome_label="faq_miss", cannot_handle=True)
    if result.data[0].get("resolution_type") == "tool":
        # Dynamic FAQ — route to the tool (Path A or C), don't return the empty answer.
        return PathOutcome(reply="", outcome_label="faq_dynamic", cannot_handle=True)
    reply = format_faq(result)
    if not reply:
        return PathOutcome(reply="", outcome_label="faq_miss", cannot_handle=True)
    return PathOutcome(reply=reply, outcome_label="faq_cache")


# ─── Path C: grounded retrieval path ─────────────────────────────────────────


async def path_c_retrieval(
    *,
    user_text: str,
    agent_turn_fn,
    budget: TurnBudget,
) -> PathOutcome:
    """Directive §2 Path C: hybrid search + optional rerank + ONE LLM call.

    ``agent_turn_fn`` is the existing ``_agent_turn`` from runner.py; this path
    wraps it to enforce the budget (one embed, one rerank, one generation).

    On budget exhaustion (the slot is already used OR the agent loop tries to
    exceed it mid-flight), returns a graceful deterministic fallback — never
    leaves the candidate without a reply.
    """
    try:
        budget.assert_can_call(CallKind.GENERATION)
        reply = await agent_turn_fn()
        budget.record_call(CallKind.GENERATION)
    except BudgetExhausted:
        return PathOutcome(
            reply="Tôi cần thêm thời gian để kiểm tra. Bạn vui lòng đợi một chút nhé.",
            outcome_label="budget_exhausted",
        )
    return PathOutcome(reply=reply, outcome_label="agent")


# ─── Path D: ambiguous clarification ─────────────────────────────────────────


async def path_d_clarify(
    *,
    top_intents: list[str],
    budget: TurnBudget,
) -> PathOutcome:
    """Directive §2 Path D: ONE clarification question (template, zero LLM)."""
    if len(top_intents) < 2:
        # Only one candidate intent — no clarification needed; signal cannot_handle.
        return PathOutcome(reply="", outcome_label="clarify_miss", cannot_handle=True)
    # Render a Vietnamese clarification asking which of the top intents the user meant.
    # Real Vietnamese intent labels would come from the router; for now we use
    # generic phrasing keyed off the intent strings.
    intent_labels: dict[str, str] = {
        "benefit_lookup": "phúc lợi",
        "working_hours_lookup": "giờ làm việc",
        "bus_schedule_lookup": "lịch xe đưa đón",
        "requirement_lookup": "yêu cầu công việc",
        "job_lookup": "thông tin việc làm",
        "faq_lookup": "câu hỏi thường gặp",
    }
    options = " hay ".join(intent_labels.get(i, i) for i in top_intents[:2])
    reply = f"Bạn đang muốn hỏi về {options} ạ? Bạn cho tôi biết chi tiết hơn để tôi hỗ trợ nhé."
    return PathOutcome(reply=reply, outcome_label="clarify")
