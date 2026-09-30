"""Bot-run schemas (read-only ops audit trail)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.conversation_messaging.domain.statuses import BotRunOutcome

MAX_DECISION_TRACE_EVENTS = 64
MAX_DECISION_TRACE_BYTES = 128 * 1024
MAX_MODEL_REASONING_CHARS = 16 * 1024


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
    "tingting_scope",
]

DecisionTraceSummaryCode = Literal[
    "empty",
    "internal_retry_prompt",
    "off_domain_terms",
    "small_talk_terms",
    "timetable_terms",
    "contact_terms",
    "vacancy_listing",
    "vacancy_terms",
    "recommendation_terms",
    "job_detail_terms",
    "employee_support_terms",
    "employee_support_continuation",
    "channel_not_allowed",
    "allowed",
    "phone_number",
    "profile_terms",
    "fallback",
    "agent_graph",
    "project_clarification",
    "direct_context",
    "focused_rag",
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
    "agent_error",
    "outbox_recovery",
    # Codes the runner records that the Literal had drifted away from (triaged
    # 2026-09-28): the recipient-unreachable stand-down, the tingting_scope
    # allow verdict, the alarmable progressive stream/answer mismatch, and the
    # support-OA clarify route.
    "recipient_unreachable",
    "progressive_stream_mismatch",
    "employee_support_clarify",
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
# "fallback" is the admin-configured quota-failover provider; a turn that
# switched providers mid-flight must still produce a valid decision trace.
DecisionTraceProvider = Literal["minimax", "openrouter", "fallback", "unknown"]
DecisionTraceModelPhase = Literal["tool_request", "final", "retry", "direct"]
DecisionTraceReasoningStatus = Literal["returned", "not_returned", "truncated"]

_DECISION_CODE_SUMMARIES: dict[str, frozenset[str]] = {
    "route_selected": frozenset(
        {
            "empty",
            "internal_retry_prompt",
            "off_domain_terms",
            "small_talk_terms",
            "timetable_terms",
            "contact_terms",
            "vacancy_listing",
            "vacancy_terms",
            "recommendation_terms",
            "job_detail_terms",
            "employee_support_terms",
            "employee_support_continuation",
            "phone_number",
            "profile_terms",
            "fallback",
        }
    ),
    "context_selected": frozenset(
        {"agent_graph", "project_clarification", "direct_context", "focused_rag"}
    ),
    "lane_selected": frozenset({"agent", "project_clarification", "direct_context"}),
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
    "degradation_reason": frozenset({"llm_throttled", "agent_error"}),
    "recovery_reason": frozenset({"outbox_recovery"}),
    # The TingTing reset flow is bound to the TingTing Zalo OA: the recruitment
    # Bot channel and Messenger must not offer it (operator requirement). On the
    # OA an unreadable message is clarified by the bot; only a confident
    # non-support intent gets the fixed hotline reply — nothing is queued
    # (operator rule 2026-09-29).
    "tingting_scope": frozenset(
        {"allowed", "channel_not_allowed", "support_clarify", "support_only_hotline"}
    ),
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


class DecisionTraceModelTurnEvent(_TraceBaseModel):
    seq: int = Field(ge=1)
    kind: Literal["model_turn"]
    turn: int = Field(ge=1)
    phase: DecisionTraceModelPhase
    provider: DecisionTraceProvider
    model: str = Field(min_length=1, max_length=128)
    reasoning_status: DecisionTraceReasoningStatus
    reasoning: str | None = Field(default=None, max_length=MAX_MODEL_REASONING_CHARS)
    tool_names: list[DecisionTraceToolName] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_reasoning_status(self) -> "DecisionTraceModelTurnEvent":
        if self.reasoning_status == "not_returned" and self.reasoning is not None:
            raise ValueError("reasoning must be absent when it was not returned")
        if self.reasoning_status != "not_returned" and not self.reasoning:
            raise ValueError("returned reasoning must contain text")
        return self


DecisionTraceEvent = Annotated[
    DecisionTraceDecisionEvent | DecisionTraceToolEvent | DecisionTraceModelTurnEvent,
    Field(discriminator="kind"),
]


class DecisionTrace(_TraceBaseModel):
    version: Literal[1, 2] = 2
    events: list[DecisionTraceEvent] = Field(max_length=MAX_DECISION_TRACE_EVENTS)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_event_sequence(self) -> "DecisionTrace":
        expected = 1
        for event in self.events:
            if event.seq != expected:
                raise ValueError("decision trace sequence must be contiguous")
            if self.version == 1 and event.kind == "model_turn":
                raise ValueError("model-turn events require decision trace version 2")
            if self.version == 2 and event.kind != "model_turn":
                raise ValueError("decision trace version 2 contains model-turn events only")
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
