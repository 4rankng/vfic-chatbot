"""Bounded, allowlisted decision-trace capture for one reactive bot run."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.schemas.bot_run import (
    DecisionTrace,
    DecisionTraceDecisionEvent,
    DecisionTraceSummaryCode,
    DecisionTraceToolEvent,
    DecisionTraceToolName,
    DecisionTraceToolSelectedBy,
    DecisionTraceCode,
    MAX_DECISION_TRACE_BYTES,
    MAX_DECISION_TRACE_EVENTS,
)

logger = logging.getLogger(__name__)

MAX_TRACE_EVENTS = MAX_DECISION_TRACE_EVENTS
MAX_TRACE_BYTES = MAX_DECISION_TRACE_BYTES


class DecisionTraceBuilder:
    """Collect a strict, size-bounded execution summary.

    This contract records observable control-flow only. Free-form model text,
    prompts, tool payloads, evidence, and exception contents are never accepted.
    """

    def __init__(
        self,
        *,
        max_events: int = MAX_TRACE_EVENTS,
        max_bytes: int = MAX_TRACE_BYTES,
    ) -> None:
        self._events: list[DecisionTraceDecisionEvent | DecisionTraceToolEvent] = []
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._truncated = False

    def record_decision(
        self,
        code: DecisionTraceCode,
        summary_code: DecisionTraceSummaryCode,
    ) -> None:
        if self._truncated:
            return
        self._append(
            DecisionTraceDecisionEvent,
            kind="decision",
            code=code,
            summary_code=summary_code,
        )

    def record_tool_selection(
        self,
        name: DecisionTraceToolName,
        *,
        selected_by: DecisionTraceToolSelectedBy,
    ) -> None:
        if self._truncated:
            return
        self._append(
            DecisionTraceToolEvent,
            kind="tool",
            name=name,
            selected_by=selected_by,
        )

    def snapshot(self) -> DecisionTrace:
        return DecisionTrace(events=list(self._events), truncated=self._truncated)

    def snapshot_payload(self) -> dict | None:
        try:
            trace = self.snapshot()
            rendered = trace.model_dump_json()
        except ValidationError:
            logger.warning("decision trace validation failed")
            return None
        except Exception:
            logger.warning("decision trace serialization failed", exc_info=True)
            return None
        if len(rendered.encode("utf-8")) > self._max_bytes:
            logger.warning("decision trace serialization exceeded size cap")
            return None
        return trace.model_dump(mode="json")

    def _append(self, event_type, **data) -> None:
        if len(self._events) >= self._max_events:
            self._truncated = True
            return
        try:
            event = event_type(seq=len(self._events) + 1, **data)
        except ValidationError:
            logger.warning("decision trace event rejected")
            return
        self._events.append(event)
        if self._serialized_size() > self._max_bytes:
            self._events.pop()
            self._truncated = True

    def _serialized_size(self) -> int:
        return len(self.snapshot().model_dump_json().encode("utf-8"))
