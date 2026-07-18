"""Bounded, allowlisted decision-trace capture for one reactive bot run."""

from __future__ import annotations

import logging
from typing import get_args

from pydantic import ValidationError

from app.schemas.bot_run import (
    DecisionTrace,
    DecisionTraceModelPhase,
    DecisionTraceModelTurnEvent,
    DecisionTraceProvider,
    DecisionTraceSummaryCode,
    DecisionTraceToolName,
    DecisionTraceToolSelectedBy,
    DecisionTraceCode,
    MAX_DECISION_TRACE_BYTES,
    MAX_DECISION_TRACE_EVENTS,
    MAX_MODEL_REASONING_CHARS,
)

logger = logging.getLogger(__name__)

MAX_TRACE_EVENTS = MAX_DECISION_TRACE_EVENTS
MAX_TRACE_BYTES = MAX_DECISION_TRACE_BYTES
_ALLOWED_MODEL_TOOL_NAMES = frozenset(get_args(DecisionTraceToolName))


class DecisionTraceBuilder:
    """Collect a strict, size-bounded trace of returned reasoning and control flow.

    Provider-returned reasoning is accepted only on model-turn events. Prompts,
    candidate answers, tool payloads/results, evidence, and exception contents
    are never accepted.
    """

    def __init__(
        self,
        *,
        max_events: int = MAX_TRACE_EVENTS,
        max_bytes: int = MAX_TRACE_BYTES,
    ) -> None:
        self._events: list[DecisionTraceModelTurnEvent] = []
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._truncated = False
        self._model_turn_count = 0

    def record_decision(
        self,
        code: DecisionTraceCode,
        summary_code: DecisionTraceSummaryCode,
    ) -> None:
        """Compatibility sink for runner instrumentation excluded from v2 traces."""

    def record_tool_selection(
        self,
        name: DecisionTraceToolName,
        *,
        selected_by: DecisionTraceToolSelectedBy,
    ) -> None:
        """Compatibility sink for policy/prefetch events excluded from v2 traces."""

    def record_model_turn(
        self,
        *,
        phase: DecisionTraceModelPhase,
        provider: DecisionTraceProvider,
        model: str,
        reasoning: str | None,
        tool_names: list[DecisionTraceToolName] | None = None,
    ) -> None:
        if self._truncated:
            return
        self._model_turn_count += 1
        normalized_reasoning = (reasoning or "").strip()
        reasoning_status = "returned"
        if not normalized_reasoning:
            normalized_reasoning = None
            reasoning_status = "not_returned"
        elif len(normalized_reasoning) > MAX_MODEL_REASONING_CHARS:
            normalized_reasoning = normalized_reasoning[:MAX_MODEL_REASONING_CHARS].rstrip()
            reasoning_status = "truncated"
        safe_tool_names = [
            name for name in tool_names or [] if name in _ALLOWED_MODEL_TOOL_NAMES
        ][:8]
        self._append(
            DecisionTraceModelTurnEvent,
            kind="model_turn",
            turn=self._model_turn_count,
            phase=phase,
            provider=provider,
            model=(model or "unknown")[:128],
            reasoning_status=reasoning_status,
            reasoning=normalized_reasoning,
            tool_names=safe_tool_names,
        )

    def snapshot(self) -> DecisionTrace:
        return DecisionTrace(version=2, events=list(self._events), truncated=self._truncated)

    def snapshot_payload(self) -> dict | None:
        try:
            trace = self.snapshot()
            rendered = trace.model_dump_json()
        except ValidationError:
            logger.warning("decision trace validation failed")
            return None
        except Exception as exc:
            logger.warning(
                "decision trace serialization failed error_type=%s",
                type(exc).__name__,
            )
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
