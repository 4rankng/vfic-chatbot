"""Unit tests for graph/safety.py — the deterministic guards (off-topic/code
detection, verdict parsing, retry builder). These implement acceptance #5
(off-topic refusal) without needing an LLM."""

import pytest

from app.graph.safety import (
    DeterministicReplyPolicy,
    fast_safety_filter,
    truncate_for_chat,
)


def test_fast_safety_clean_reply_needs_no_llm():
    out = fast_safety_filter("Chào bạn, bạn muốn tìm việc ở khu vực nào?")
    assert out["needs_llm_safety"] is False
    assert out["empty_after_clean"] is False
    assert out["retryable_empty"] is False
    assert out["safe_to_send"] is True
    assert out["issue_type"] == "none"


def test_fast_safety_strips_markdown_and_does_not_flag_cleaned_code():
    # Markdown bold/headers/code fences are stripped before the risk scan. A
    # reply whose cleaned form is plain prose must NOT trip the fallback —
    # regression for the production bug where "Mình không trả lời được..."
    # replaced a legitimate answer that merely contained a code fence.
    out = fast_safety_filter("Đây là **code** python: ```print(1)``` bạn nhé.")
    assert out["needs_llm_safety"] is False
    assert out["safe_to_send"] is True
    assert "```" not in out["output"]
    assert "**" not in out["output"]


def test_fast_safety_risk_scan_ignores_raw_fences_but_keeps_true_leakage():
    # A stray code fence inside a real recruitment answer is cleaned away and
    # must not discard the reply. Regression for the production bug where a
    # fence in the agent output replaced the whole answer with the generic
    # "Mình không trả lời được..." fallback.
    legit_with_fence = (
        "Bạn cần mang theo CCCD. ```print(1)``` Hẹn gặp bạn lúc 8h sáng nhé."
    )
    out_legit = fast_safety_filter(legit_with_fence)
    assert out_legit["needs_llm_safety"] is False
    assert out_legit["safe_to_send"] is True
    assert "CCCD" in out_legit["output"]
    assert "```" not in out_legit["output"]


def test_fast_safety_does_not_flag_tech_words_in_prose():
    # Bare tech words (code/api/database/workflow) in natural prose must NOT
    # escalate to the 10s+ LLM safety judge — they appear legitimately in job
    # descriptions ("cần biết SQL", "làm việc với database", "viết code").
    out = fast_safety_filter("Công việc yêu cầu bạn biết code, gọi api và dùng database.")
    assert out["needs_llm_safety"] is False
    assert out["safe_to_send"] is True


def test_fast_safety_too_long_flagged():
    out = fast_safety_filter("x" * 2000)
    assert out["needs_llm_safety"] is True


def test_fast_safety_strips_minimax_think_reasoning():
    # MiniMax M2 reasoning models emit <think>…</think>; the deliberation must
    # never reach the user — only the reply after </think> is sent.
    out = fast_safety_filter("<think>internal reasoning SECRETKEY here</think>Chào bạn! 😊")
    assert "SECRETKEY" not in out["output"]
    assert "<think>" not in out["output"]
    assert out["output"].startswith("Chào bạn")


def test_fast_safety_exposes_reasoning_only_output_as_empty_after_clean():
    out = fast_safety_filter("<think>internal reasoning only</think>")

    assert out["empty_after_clean"] is True
    assert out["retryable_empty"] is True
    assert out["needs_llm_safety"] is True
    # Nothing sendable survived cleaning — the output stays empty and the turn
    # keeps quiet (no canned redirect).
    assert out["output"] == ""


@pytest.mark.parametrize(
    "raw",
    [
        "<think>internal reasoning ended before the closing tag",
        "<think\ninternal reasoning after a truncated opener",
        "<think internal reasoning after a malformed opener",
        "< think>internal reasoning after a spaced opener",
    ],
)
def test_fast_safety_discards_unclosed_minimax_think_reasoning(raw):
    out = fast_safety_filter(raw)

    assert out["empty_after_clean"] is True
    assert out["needs_llm_safety"] is True
    assert "internal reasoning" not in out["output"]


@pytest.mark.parametrize(
    "raw",
    [
        "<think\ninternal reasoning after a truncated opener",
        "< think>internal reasoning after a spaced opener",
    ],
)
def test_reply_policy_fails_closed_on_malformed_think_openers(raw):
    result = DeterministicReplyPolicy().finalize(
        raw,
        generated=True,
        user_text="Rorze còn tuyển không?",
    )

    assert "internal reasoning" not in result.output
    assert result.verdict == "empty_after_clean"


@pytest.mark.parametrize(
    "raw",
    [
        '<think>tool_call: {"safe_to_send": false}</think>',
        "```tool_call```",
    ],
)
def test_fast_safety_retries_any_output_that_cleans_to_empty(raw):
    """Nothing survived cleaning, so there is text to regenerate, not to judge."""
    out = fast_safety_filter(raw)

    assert out["empty_after_clean"] is True
    assert out["retryable_empty"] is True


def test_truncate_for_chat_keeps_short_text_and_cuts_at_word_boundary():
    assert truncate_for_chat("ngắn gọn") == "ngắn gọn"
    long_text = " ".join(["việc"] * 400)  # well over 1800 chars, space-separated
    out = truncate_for_chat(long_text)
    assert len(out) <= 1802  # ~1800 + ellipsis
    assert out.endswith(" …")
    assert "việc" in out


def test_truncate_for_chat_hard_cut_when_no_space():
    out = truncate_for_chat("x" * 2000)
    assert out == "x" * 1800 + " …"


def test_fast_safety_truncates_overlong_output_deterministically():
    out = fast_safety_filter(" ".join(["việc"] * 400))
    assert out["needs_llm_safety"] is True
    assert len(out["output"]) <= 1802
    assert out["output"].endswith(" …")


@pytest.mark.parametrize(
    "raw",
    [
        # Ordinary recruitment Vietnamese that the removed lexical blocklist used
        # to discard wholesale. "đóng vai trò" means "plays a role"; "lồng ghép"
        # merely contains the profanity substring "lồn"; "bỏ qua yêu cầu bằng
        # cấp" waives a requirement; "hướng dẫn mới" is routine HR prose.
        "Anh sẽ đóng vai trò công nhân sản xuất tại chuyền kiểm tra màn hình.",
        "Chương trình đào tạo có lồng ghép hướng dẫn an toàn lao động.",
        "Công ty vừa ban hành hướng dẫn mới về thủ tục nhận việc.",
        "Công ty bỏ qua yêu cầu bằng cấp và kinh nghiệm ạ.",
        "Sau thử việc, bạn sẽ là nhân viên chính thức.",
        "Làm ở LG Display là sản xuất và kiểm tra màn hình tivi, máy tính, điện thoại.",
    ],
)
def test_reply_policy_delivers_legitimate_recruitment_replies_unchanged(raw):
    """No keyword may discard a reply; only shape (empty / over-long) may act."""
    result = DeterministicReplyPolicy().finalize(
        raw, generated=True, user_text="làm ở LG là làm những gì"
    )

    assert result.verdict == "passed"
    assert result.output == raw
    assert result.trigger is None


def test_grounded_job_description_reply_is_delivered_unchanged():
    """Regression: prod bot_run 613 lost a correct, tool-grounded answer to the blocklist."""
    reply = (
        "Làm tại LG Display là sản xuất và kiểm tra màn hình tivi, máy tính, điện thoại ạ. "
        "Công ty đào tạo trước khi vào làm, không yêu cầu kinh nghiệm hay bằng cấp. "
        "Anh/chị cho em xin năm sinh để em kiểm tra điều kiện nhé ạ?"
    )
    result = DeterministicReplyPolicy().finalize(
        reply, generated=True, user_text="làm ở LG là làm những gì"
    )

    assert result.verdict == "passed"
    assert result.output == reply


def test_reply_policy_only_acts_on_structural_conditions():
    """Empty-after-cleaning still falls back; nothing else is intercepted."""
    empty = DeterministicReplyPolicy().finalize(
        "<think>only deliberation</think>", generated=True, user_text="bất kỳ"
    )
    assert empty.verdict == "empty_after_clean"

    long_reply = " ".join(["việc"] * 400)
    truncated = DeterministicReplyPolicy().finalize(
        long_reply, generated=True, user_text="bất kỳ"
    )
    assert truncated.verdict == "truncated"
    assert truncated.output.endswith(" …")
