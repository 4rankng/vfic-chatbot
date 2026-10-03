"""Pins for the agent-lane history budget in ``build_agent_user_text``.

The direct-context lane already caps injected history; this lane previously
injected up to 16 recent messages with no budget. These pins lock the bounded
behavior: newest turns survive, the oldest are dropped whole, and the elision is
marked so the model knows older context was left out.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.direct_context import build_direct_user_text
from app.graph.proactive import _build_proactive_user_text
from app.graph.prompt_context import (
    _HISTORY_ELISION_MARKER,
    _HISTORY_TRUNCATION_SUFFIX,
    _MAX_HISTORY_CHARS,
    build_agent_user_text,
)
from tests.test_text_tool_calls import _DSML_LEAK


def _message(body: str, *, sender: str = "WORKER"):
    return SimpleNamespace(sender=sender, body=body, delivery_status="DELIVERED")


def test_history_budget_keeps_newest_and_marks_elision():
    history = [_message(f"tin {i} " + "x" * 1000) for i in range(20)]

    out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=history,
    )

    assert _HISTORY_ELISION_MARKER.format(count=15) in out
    assert "tin 19" in out  # newest survives
    assert "tin 0 " not in out  # oldest dropped whole
    # The current candidate message is appended separately and never cut.
    assert "câu hỏi hiện tại" in out


def test_history_budget_truncates_a_single_oversized_message():
    history = [_message("x" * (_MAX_HISTORY_CHARS * 2), sender="BOT")]

    out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=history,
    )

    assert _HISTORY_TRUNCATION_SUFFIX in out
    assert "câu hỏi hiện tại" in out


def test_history_within_budget_is_unmarked_and_complete():
    history = [_message(f"tin {i}") for i in range(3)]

    out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=history,
    )

    assert "tin 0" in out and "tin 1" in out and "tin 2" in out
    assert _HISTORY_ELISION_MARKER.format(count=1) not in out
    assert _HISTORY_TRUNCATION_SUFFIX not in out


def test_suppressed_messages_are_excluded_before_budgeting():
    history = [
        _message("tin đã chặn"),
        SimpleNamespace(sender="BOT", body="phản hồi", delivery_status="SUPPRESSED"),
        _message("tin cuối"),
    ]

    out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=history,
    )

    assert "tin đã chặn" in out
    assert "phản hồi" not in out
    assert "tin cuối" in out


def test_a_replayed_bot_body_can_no_longer_carry_markup_into_the_prompt():
    """A leak delivered once is persisted verbatim; replaying it teaches the
    dialect. Every history renderer strips it — and only from BOT bodies."""
    leaked = "Dạ em kiểm tra ngay ạ.\n" + _DSML_LEAK
    bot = _message(leaked, sender="BOT")
    bot_only = _message(_DSML_LEAK, sender="BOT")
    bot_history = [bot, bot_only]

    out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=bot_history,
    )

    assert "Dạ em kiểm tra ngay ạ." in out
    assert "invoke" not in out and "DSML" not in out
    # The markup-only BOT body contributes no line at all.
    assert out.count("- Bot:") == 1

    # Candidate-authored text is never altered, even when it quotes the markup.
    worker = _message("em hỏi chút\n" + _DSML_LEAK, sender="WORKER")
    worker_out = build_agent_user_text(
        chat_id="c1",
        current_user_text="câu hỏi hiện tại",
        recent_messages=[worker],
    )

    assert worker.body in worker_out

    # The other two history renderers hold the same line as the agent lane.
    for rendered in (
        build_direct_user_text(
            current_user_text="câu hỏi hiện tại",
            recent_messages=bot_history,
            history_token_budget=12_000,
        ),
        _build_proactive_user_text(chat_id="c1", recent_messages=bot_history),
    ):
        assert "Dạ em kiểm tra ngay ạ." in rendered
        assert "invoke" not in rendered and "DSML" not in rendered
        assert rendered.count("- Bot:") == 1
