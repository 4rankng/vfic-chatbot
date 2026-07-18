from __future__ import annotations

import logging

import pytest

from app.graph.decision_trace import DecisionTraceBuilder
from app.graph.schemas import _dispatch_tool
from app.schemas.bot_run import MAX_DECISION_TRACE_EVENTS, parse_decision_trace


def test_trace_contract_rejects_unknown_and_sensitive_fields() -> None:
    payload = {
        "version": 1,
        "events": [
            {
                "seq": 1,
                "kind": "tool",
                "name": "search_knowledge",
                "selected_by": "model",
                "args": {"query": "SENTINEL_PHONE_0900000000"},
            }
        ],
        "truncated": False,
    }

    assert parse_decision_trace(payload) is None


def test_trace_contract_requires_contiguous_sequence() -> None:
    payload = {
        "version": 1,
        "events": [
            {
                "seq": 2,
                "kind": "decision",
                "code": "route_selected",
                "summary_code": "fallback",
            }
        ],
        "truncated": False,
    }

    assert parse_decision_trace(payload) is None


def test_builder_is_bounded_and_marks_truncation() -> None:
    builder = DecisionTraceBuilder()
    for _ in range(MAX_DECISION_TRACE_EVENTS + 1):
        builder.record_decision("route_selected", "fallback")

    payload = builder.snapshot_payload()

    assert payload is not None
    assert len(payload["events"]) == MAX_DECISION_TRACE_EVENTS
    assert payload["truncated"] is True
    assert parse_decision_trace(payload) is not None


def test_builder_rejects_invalid_event_without_logging_value(caplog) -> None:
    builder = DecisionTraceBuilder()
    sentinel = "SENTINEL_CANDIDATE_TEXT"

    with caplog.at_level(logging.WARNING):
        builder.record_decision("route_selected", sentinel)  # type: ignore[arg-type]

    assert builder.snapshot_payload() == {"version": 1, "events": [], "truncated": False}
    assert sentinel not in caplog.text


@pytest.mark.asyncio
async def test_tool_dispatch_logs_neither_arguments_nor_exception_content(
    caplog, monkeypatch
) -> None:
    sentinel = "SENTINEL_PHONE_0900000000"

    class _Retrieval:
        async def search_knowledge(self, *_args, **_kwargs):
            raise RuntimeError(sentinel)

    with caplog.at_level(logging.WARNING):
        await _dispatch_tool(
            _Retrieval(),
            None,
            "unknown_tool",
            {"query": sentinel},
        )

    assert sentinel not in caplog.text

