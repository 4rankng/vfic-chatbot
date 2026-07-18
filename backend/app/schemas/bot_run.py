"""Bot-run schemas (read-only ops audit trail)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.conversation import BotRunOutcome

MAX_DECISION_TRACE_EVENTS = 32
MAX_DECISION_TRACE_BYTES = 16 * 1024


class _TraceBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


DecisionTraceCode = Literal[
    "route_selected",
    "context_selected",
    "lane_selected",
    "model_selected",
    "required_tool_selected",
    "safety_verdict",
    "grounding_verdict",
    "ownership_verdict",
    "degradation_reason",
    "recovery_reason",
]

DecisionTraceSummaryCode = Literal[
    "empty",
    "internal_retry_prompt",
    "off_domain_terms",
    "fast_lane_match",
    "timetable_terms",
    "contact_terms",
    "vacancy_listing",
    "vacancy_terms",
    "recommendation_terms",
    "job_detail_terms",
    "phone_number",
    "profile_terms",
    "fallback",
    "agent_graph",
    "project_clarification",
    "direct_context",
    "focused_rag",
    "faq_bypass",
    "agent",
    "primary",
    "fast",
    "direct",
    "search_user_memory",
    "list_active_jobs",
    "list_active_projects",
    "search_knowledge",
    "recommend_projects",
    "recommend_jobs",
    "search_bus_timetable",
    "get_product_features",
    "passed",
    "blocklist_redirect",
    "risk_redirect",
    "truncated",
    "empty_after_clean",
    "grounded",
    "sanitized",
    "skipped",
    "claimed",
    "suppressed",
    "llm_throttled",
    "outbox_recovery",
]

DecisionTraceToolName = Literal[
    "search_user_memory",
    "list_active_jobs",
    "list_active_projects",
    "search_knowledge",
    "recommend_projects",
    "recommend_jobs",
    "search_bus_timetable",
    "get_product_features",
]

DecisionTraceToolSelectedBy = Literal["model", "policy", "prefetch"]

_DECISION_CODE_SUMMARIES: dict[str, frozenset[str]] = {
    "route_selected": frozenset(
        {
            "empty",
            "internal_retry_prompt",
            "off_domain_terms",
            "fast_lane_match",
            "timetable_terms",
            "contact_terms",
            "vacancy_listing",
            "vacancy_terms",
            "recommendation_terms",
            "job_detail_terms",
            "phone_number",
            "profile_terms",
            "fallback",
        }
    ),
    "context_selected": frozenset(
        {"agent_graph", "project_clarification", "direct_context", "focused_rag", "faq_bypass"}
    ),
    "lane_selected": frozenset({"agent", "project_clarification", "direct_context", "faq_bypass"}),
    "model_selected": frozenset({"primary", "fast", "direct"}),
    "required_tool_selected": frozenset(
        {
            "search_user_memory",
            "list_active_jobs",
            "list_active_projects",
            "search_knowledge",
            "recommend_projects",
            "recommend_jobs",
            "search_bus_timetable",
            "get_product_features",
        }
    ),
    "safety_verdict": frozenset(
        {"passed", "blocklist_redirect", "risk_redirect", "truncated", "empty_after_clean"}
    ),
    "grounding_verdict": frozenset({"grounded", "sanitized", "skipped"}),
    "ownership_verdict": frozenset({"claimed", "suppressed"}),
    "degradation_reason": frozenset({"llm_throttled"}),
    "recovery_reason": frozenset({"outbox_recovery"}),
}


class DecisionTraceDecisionEvent(_TraceBaseModel):
    seq: int = Field(ge=1)
    kind: Literal["decision"]
    code: DecisionTraceCode
    summary_code: DecisionTraceSummaryCode

    @model_validator(mode="after")
    def validate_code_summary_pair(self) -> "DecisionTraceDecisionEvent":
        allowed = _DECISION_CODE_SUMMARIES[self.code]
        if self.summary_code not in allowed:
            raise ValueError("summary_code is not allowed for this decision code")
        return self


class DecisionTraceToolEvent(_TraceBaseModel):
    seq: int = Field(ge=1)
    kind: Literal["tool"]
    name: DecisionTraceToolName
    selected_by: DecisionTraceToolSelectedBy


DecisionTraceEvent = Annotated[
    DecisionTraceDecisionEvent | DecisionTraceToolEvent,
    Field(discriminator="kind"),
]


class DecisionTrace(_TraceBaseModel):
    version: Literal[1] = 1
    events: list[DecisionTraceEvent] = Field(max_length=MAX_DECISION_TRACE_EVENTS)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_event_sequence(self) -> "DecisionTrace":
        expected = 1
        for event in self.events:
            if event.seq != expected:
                raise ValueError("decision trace sequence must be contiguous")
            expected += 1
        return self


def parse_decision_trace(value: object) -> DecisionTrace | None:
    if value is None:
        return None
    try:
        trace = DecisionTrace.model_validate(value)
        rendered = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        if len(rendered.encode("utf-8")) > MAX_DECISION_TRACE_BYTES:
            return None
        return trace
    except (TypeError, ValueError, ValidationError):
        return None


class BotRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    version_at_start: int
    proposed_reply: str | None = None
    outcome: BotRunOutcome


class BotRunListResponse(BaseModel):
    data: list[BotRunOut]
    total: int


class BotRunTraceSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    outcome: BotRunOutcome
    trace_available: bool


class BotRunTraceSummaryListResponse(BaseModel):
    data: list[BotRunTraceSummaryOut]
    total: int


class BotRunTraceDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    outcome: BotRunOutcome
    trace_available: bool
    decision_trace: DecisionTrace | None = None
