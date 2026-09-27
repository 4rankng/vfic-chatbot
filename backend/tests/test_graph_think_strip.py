"""Unit tests for graph/think_strip.py — provider reasoning stripping.

The pre-send answer review layer that used to live in ``graph/safety.py``
(``fast_safety_filter``, ``DeterministicReplyPolicy``, ``truncate_for_chat``)
was removed on explicit operator instruction; the agent's answer now ships as
generated. One invariant remains: provider reasoning must never reach a
candidate, so every user-visible reply passes through
:func:`strip_think_reasoning` exactly once at the converged boundary.
"""

import pytest

from app.graph.think_strip import (
    extract_text_tool_calls,
    strip_provider_artifacts,
    strip_think_reasoning,
    strip_tool_call_markup,
    visible_offset,
)


def test_strip_think_reasoning_removes_complete_block():
    # MiniMax M2 reasoning models emit  thinking…</think>; the deliberation must
    # never reach the user — only the reply after the closing tag is sent.
    out = strip_think_reasoning(
        " thinkinginternal reasoning SECRETKEY here</think>Chào bạn! 😊"
    )
    assert "SECRETKEY" not in out
    assert " thinking" not in out
    assert out.startswith("Chào bạn")


def test_strip_think_reasoning_of_reasoning_only_output_is_empty():
    out = strip_think_reasoning(" thinkinginternal reasoning only</think>")

    assert out == ""


def test_strip_think_reasoning_keeps_plain_reply_untouched():
    # A reply with no think tags is the user-visible answer as generated.
    out = strip_think_reasoning("Chào bạn, bạn muốn tìm việc ở khu vực nào?")

    assert out == "Chào bạn, bạn muốn tìm việc ở khu vực nào?"


@pytest.mark.parametrize(
    "raw",
    [
        "<think\ninternal reasoning after a truncated opener",
        "<think internal reasoning after a malformed opener",
        "< think>internal reasoning after a spaced opener",
    ],
)
def test_strip_think_reasoning_discards_unclosed_minimax_think_reasoning(raw):
    out = strip_think_reasoning(raw)

    assert "internal reasoning" not in out
    assert out == ""


def test_visible_offset_is_zero_without_think():
    # No deliberation: candidate-visible text starts at the very beginning.
    assert visible_offset("Chào bạn!") == 0
    assert visible_offset("") == 0
    assert visible_offset(None) == 0


def test_visible_offset_points_past_the_last_closing_tag():
    raw = "\u003cthink\u003eSECRET\u003c/think\u003emid \u003cthink\u003emore\u003c/think\u003eChào bạn!"

    assert visible_offset(raw) == raw.index("Chào bạn!")


def test_visible_offset_is_none_while_a_think_block_is_open():
    # Deliberation still streaming: nothing is visible yet, so the progressive
    # sender must not spend its wait cap or look for a boundary.
    assert visible_offset("\u003cthink\u003ereasoning") is None
    assert visible_offset("mid \u003cthink\u003estill thinking") is None


# ── Tool-call markup written as content ─────────────────────────────────────
# Production delivered `<invoke name="search_knowledge">…` to a candidate: the
# provider serialized its call into the content instead of the tool_calls field.

_LEAKED_REPLY = (
    "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ.\n"
    '<invoke name="search_knowledge">\n'
    '<parameter name="query">hotline liên hệ VFIC số điện thoại admin</parameter>\n'
    "</invoke>"
)


def test_extract_text_tool_calls_reads_the_invoke_block():
    calls = extract_text_tool_calls(_LEAKED_REPLY)
    assert calls == [
        {
            "name": "search_knowledge",
            "args": {"query": "hotline liên hệ VFIC số điện thoại admin"},
            "id": "text-call-1",
        }
    ]


def test_extract_text_tool_calls_reads_several_calls_in_order():
    raw = (
        '<invoke name="search_knowledge"><parameter name="query">a</parameter></invoke>'
        '<invoke name="list_active_jobs"><parameter name="top_k">5</parameter></invoke>'
    )
    calls = extract_text_tool_calls(raw)
    assert [call["name"] for call in calls] == ["search_knowledge", "list_active_jobs"]
    assert calls[1]["args"] == {"top_k": 5}  # a JSON-shaped value keeps its type


def test_extract_text_tool_calls_ignores_a_nameless_block():
    assert extract_text_tool_calls('<invoke><parameter name="q">x</parameter></invoke>') == []


def test_strip_tool_call_markup_removes_the_block_and_keeps_the_prose():
    assert strip_tool_call_markup(_LEAKED_REPLY).strip() == (
        "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ."
    )


def test_strip_tool_call_markup_drops_an_unclosed_block():
    """A call cut mid-generation is not a reply: nothing after it may ship."""
    assert strip_tool_call_markup('Chào anh. <invoke name="search_knowledge"> <param') == "Chào anh. "


def test_strip_tool_call_markup_removes_a_lone_closing_tag():
    assert strip_tool_call_markup("Nội dung\n</invoke>") == "Nội dung\n"


def test_strip_provider_artifacts_handles_thinking_and_markup_together():
    raw = " thinkingdeliberation here</think>" + _LEAKED_REPLY
    assert strip_provider_artifacts(raw).strip() == (
        "Dạ, để em kiểm tra thông tin liên hệ của VFIC ngay ạ."
    )


def test_strip_provider_artifacts_keeps_a_plain_reply_untouched():
    assert strip_provider_artifacts("Dạ có ạ.") == "Dạ có ạ."
