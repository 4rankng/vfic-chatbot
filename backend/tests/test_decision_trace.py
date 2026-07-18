from __future__ import annotations

import logging

import pytest

from app.graph.decision_trace import DecisionTraceBuilder
from app.graph.schemas import _dispatch_tool
from app.schemas.bot_run import (
    MAX_DECISION_TRACE_EVENTS,
    MAX_MODEL_REASONING_CHARS,
    parse_decision_trace,
)


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


def test_trace_contract_rejects_answer_tool_payloads_and_results_on_model_turn() -> None:
    base_event = {
        "seq": 1,
        "kind": "model_turn",
        "turn": 1,
        "phase": "tool_request",
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "reasoning_status": "returned",
        "reasoning": "Cần tra cứu lịch xe.",
        "tool_names": ["search_bus_timetable"],
    }
    for forbidden_field, value in (
        ("final_answer", "SENTINEL_CANDIDATE_ANSWER"),
        ("tool_args", {"question": "SENTINEL_PRIVATE_QUERY"}),
        ("tool_results", ["SENTINEL_PRIVATE_RESULT"]),
    ):
        event = {**base_event, forbidden_field: value}
        payload = {"version": 2, "events": [event], "truncated": False}

        assert parse_decision_trace(payload) is None


def test_trace_contract_keeps_version_one_legacy_only() -> None:
    payload = {
        "version": 1,
        "events": [
            {
                "seq": 1,
                "kind": "model_turn",
                "turn": 1,
                "phase": "final",
                "provider": "openrouter",
                "model": "model",
                "reasoning_status": "not_returned",
                "reasoning": None,
                "tool_names": [],
            }
        ],
        "truncated": False,
    }

    assert parse_decision_trace(payload) is None


def test_builder_is_bounded_and_marks_truncation() -> None:
    builder = DecisionTraceBuilder()
    for _ in range(MAX_DECISION_TRACE_EVENTS + 1):
        builder.record_model_turn(
            phase="final",
            provider="minimax",
            model="MiniMax-M2.7",
            reasoning=None,
        )

    payload = builder.snapshot_payload()

    assert payload is not None
    assert len(payload["events"]) == MAX_DECISION_TRACE_EVENTS
    assert payload["truncated"] is True
    assert parse_decision_trace(payload) is not None


def test_builder_rejects_invalid_event_without_logging_value(caplog) -> None:
    builder = DecisionTraceBuilder()
    sentinel = "SENTINEL_CANDIDATE_TEXT"

    with caplog.at_level(logging.WARNING):
        builder.record_model_turn(
            phase="final",
            provider=sentinel,  # type: ignore[arg-type]
            model="MiniMax-M2.7",
            reasoning="safe reasoning",
        )

    assert builder.snapshot_payload() == {"version": 2, "events": [], "truncated": False}
    assert sentinel not in caplog.text


def test_builder_keeps_reasoning_when_model_returns_unknown_tool_name() -> None:
    builder = DecisionTraceBuilder()

    builder.record_model_turn(
        phase="tool_request",
        provider="minimax",
        model="MiniMax-M2.7",
        reasoning="I should use the provider-specific tool.",
        tool_names=["provider_private_tool"],  # type: ignore[list-item]
    )

    event = builder.snapshot_payload()["events"][0]
    assert event["reasoning"] == "I should use the provider-specific tool."
    assert event["tool_names"] == []


def test_version_two_rejects_legacy_execution_summary_events() -> None:
    payload = {
        "version": 2,
        "events": [
            {
                "seq": 1,
                "kind": "decision",
                "code": "route_selected",
                "summary_code": "fallback",
            }
        ],
        "truncated": False,
    }

    assert parse_decision_trace(payload) is None


def test_builder_records_reasoning_and_selected_tools_per_model_turn() -> None:
    builder = DecisionTraceBuilder()

    builder.record_model_turn(
        phase="tool_request",
        provider="minimax",
        model="MiniMax-M2.7",
        reasoning="  Cần tra cứu dữ liệu tuyển dụng.  ",
        tool_names=["search_knowledge"],
    )
    builder.record_model_turn(
        phase="final",
        provider="minimax",
        model="MiniMax-M2.7",
        reasoning=None,
    )

    payload = builder.snapshot_payload()

    assert payload is not None
    assert payload["version"] == 2
    first, second = payload["events"]
    assert first == {
        "seq": 1,
        "kind": "model_turn",
        "turn": 1,
        "phase": "tool_request",
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "reasoning_status": "returned",
        "reasoning": "Cần tra cứu dữ liệu tuyển dụng.",
        "tool_names": ["search_knowledge"],
    }
    assert second["turn"] == 2
    assert second["reasoning_status"] == "not_returned"
    assert second["reasoning"] is None
    assert second["tool_names"] == []


def test_builder_truncates_each_returned_reasoning_block() -> None:
    builder = DecisionTraceBuilder()

    builder.record_model_turn(
        phase="final",
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        reasoning="x" * (MAX_MODEL_REASONING_CHARS + 100),
    )

    event = builder.snapshot_payload()["events"][0]
    assert event["reasoning_status"] == "truncated"
    assert len(event["reasoning"]) == MAX_MODEL_REASONING_CHARS


def test_builder_stops_before_total_trace_size_cap() -> None:
    builder = DecisionTraceBuilder(max_bytes=700)
    for _ in range(10):
        builder.record_model_turn(
            phase="final",
            provider="openrouter",
            model="deepseek/deepseek-v4-flash",
            reasoning="x" * 200,
        )

    payload = builder.snapshot_payload()

    assert payload is not None
    assert payload["truncated"] is True
    assert 0 < len(payload["events"]) < 10


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
