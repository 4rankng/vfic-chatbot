"""Unit tests for graph/safety.py — provider reasoning stripping.

The pre-send answer review layer that used to live in ``graph/safety.py``
(``fast_safety_filter``, ``DeterministicReplyPolicy``, ``truncate_for_chat``)
was removed on explicit operator instruction; the agent's answer now ships as
generated. One invariant remains: provider reasoning must never reach a
candidate, so every user-visible reply passes through
:func:`strip_think_reasoning` exactly once at the converged boundary.
"""

import pytest

from app.graph.safety import strip_think_reasoning


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
