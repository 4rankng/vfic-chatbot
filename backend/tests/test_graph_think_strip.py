"""Unit tests for graph/think_strip.py â provider reasoning stripping.

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
    strip_markdown_decorations,
    strip_provider_artifacts,
    strip_think_reasoning,
    strip_tool_call_markup,
    visible_offset,
)


def test_strip_think_reasoning_removes_complete_block():
    # MiniMax M2 reasoning models emit  thinkingâ¦</think>; the deliberation must
    # never reach the user â only the reply after the closing tag is sent.
    out = strip_think_reasoning(
        " thinkinginternal reasoning SECRETKEY here</think>ChÃ o báº¡n! ð"
    )
    assert "SECRETKEY" not in out
    assert " thinking" not in out
    assert out.startswith("ChÃ o báº¡n")


def test_strip_think_reasoning_of_reasoning_only_output_is_empty():
    out = strip_think_reasoning(" thinkinginternal reasoning only</think>")

    assert out == ""


def test_strip_think_reasoning_keeps_plain_reply_untouched():
    # A reply with no think tags is the user-visible answer as generated.
    out = strip_think_reasoning("ChÃ o báº¡n, báº¡n muá»n tÃ¬m viá»c á» khu vá»±c nÃ o?")

    assert out == "ChÃ o báº¡n, báº¡n muá»n tÃ¬m viá»c á» khu vá»±c nÃ o?"


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
    assert visible_offset("ChÃ o báº¡n!") == 0
    assert visible_offset("") == 0
    assert visible_offset(None) == 0


def test_visible_offset_points_past_the_last_closing_tag():
    raw = "\u003cthink\u003eSECRET\u003c/think\u003emid \u003cthink\u003emore\u003c/think\u003eChÃ o báº¡n!"

    assert visible_offset(raw) == raw.index("ChÃ o báº¡n!")


def test_visible_offset_is_none_while_a_think_block_is_open():
    # Deliberation still streaming: nothing is visible yet, so the progressive
    # sender must not spend its wait cap or look for a boundary.
    assert visible_offset("\u003cthink\u003ereasoning") is None
    assert visible_offset("mid \u003cthink\u003estill thinking") is None


# ââ Tool-call markup written as content âââââââââââââââââââââââââââââââââââââ
# Production delivered `<invoke name="search_knowledge">â¦` to a candidate: the
# provider serialized its call into the content instead of the tool_calls field.

_LEAKED_REPLY = (
    "Dáº¡, Äá» em kiá»m tra thÃ´ng tin liÃªn há» cá»§a VFIC ngay áº¡.\n"
    '<invoke name="search_knowledge">\n'
    '<parameter name="query">hotline liÃªn há» VFIC sá» Äiá»n thoáº¡i admin</parameter>\n'
    "</invoke>"
)


def test_extract_text_tool_calls_reads_the_invoke_block():
    calls = extract_text_tool_calls(_LEAKED_REPLY)
    assert calls == [
        {
            "name": "search_knowledge",
            "args": {"query": "hotline liÃªn há» VFIC sá» Äiá»n thoáº¡i admin"},
            "id": "text-call-1",
        }
    ]


def test_extract_text_tool_calls_reads_several_calls_in_order():
    raw = (
        '<invoke name="search_knowledge"><parameter name="query">a</parameter></invoke>'
        '<invoke name="list_active_projects"><parameter name="salary_min_vnd">8000000</parameter></invoke>'
    )
    calls = extract_text_tool_calls(raw)
    assert [call["name"] for call in calls] == ["search_knowledge", "list_active_projects"]
    assert calls[1]["args"] == {"salary_min_vnd": 8000000}  # a JSON-shaped value keeps its type


def test_extract_text_tool_calls_ignores_a_nameless_block():
    assert extract_text_tool_calls('<invoke><parameter name="q">x</parameter></invoke>') == []


def test_strip_tool_call_markup_removes_the_block_and_keeps_the_prose():
    assert strip_tool_call_markup(_LEAKED_REPLY).strip() == (
        "Dáº¡, Äá» em kiá»m tra thÃ´ng tin liÃªn há» cá»§a VFIC ngay áº¡."
    )


def test_strip_tool_call_markup_drops_an_unclosed_block():
    """A call cut mid-generation is not a reply: nothing after it may ship."""
    assert strip_tool_call_markup('ChÃ o anh. <invoke name="search_knowledge"> <param') == "ChÃ o anh. "


def test_strip_tool_call_markup_removes_a_lone_closing_tag():
    assert strip_tool_call_markup("Ná»i dung\n</invoke>") == "Ná»i dung\n"


def test_strip_provider_artifacts_handles_thinking_and_markup_together():
    raw = " thinkingdeliberation here</think>" + _LEAKED_REPLY
    assert strip_provider_artifacts(raw).strip() == (
        "Dáº¡, Äá» em kiá»m tra thÃ´ng tin liÃªn há» cá»§a VFIC ngay áº¡."
    )


def test_strip_provider_artifacts_keeps_a_plain_reply_untouched():
    assert strip_provider_artifacts("Dáº¡ cÃ³ áº¡.") == "Dáº¡ cÃ³ áº¡."


def test_strip_markdown_decorations_strips_bold_italics_and_code():
    raw = "Dạ, **4P Electronics**: làm linh kiện. `KPI` đạt ~~cao~~ *ổn* __đảm bảo__."
    assert strip_markdown_decorations(raw) == (
        "Dạ, 4P Electronics: làm linh kiện. KPI đạt cao ổn đảm bảo."
    )


def test_strip_markdown_decorations_downgrades_links_and_headings():
    raw = "### Cơ hội việc làm\n[Xem trang tuyển dụng](https://vficmanpower.com) nhé ạ."
    assert strip_markdown_decorations(raw) == (
        "Cơ hội việc làm\nXem trang tuyển dụng (https://vficmanpower.com) nhé ạ."
    )


def test_strip_markdown_decorations_keeps_plain_list_structure():
    raw = "- **Rorze**: đứng máy CNC\n\n\n- **Kho**: đóng gói hàng"
    # Whitespace is preserved exactly (progressive bubble offsets depend on it).
    assert strip_markdown_decorations(raw) == (
        "- Rorze: đứng máy CNC\n\n\n- Kho: đóng gói hàng"
    )


def test_strip_markdown_decorations_leaves_plain_text_untouched():
    plain = "Dạ bên em đang tuyển vị trí kho hàng tại Hải Phòng ạ.\n\nAnh/chị 18-45 tuổi nhé ạ."
    assert strip_markdown_decorations(plain) == plain


def test_strip_markdown_decorations_drops_replacement_characters():
    """Provider hiccups emit U+FFFD mid-word; the reply must never ship it."""
    raw = "gần Thuỷ Ng\ufffduyên hơn, để \ufffdn điện thoại nhé ạ"
    assert strip_markdown_decorations(raw) == (
        "gần Thuỷ Nguyên hơn, để n điện thoại nhé ạ"
    )


def test_next_sendable_offset_skips_terminators_inside_parentheses():
    """The observed production cut orphaned the ')' of '(...huyện ngoài ạ?)'."""
    from app.graph.progressive import _next_sendable_offset

    raw = "Để em hỏi: (nội thành Hải Phòng hay huyện ngoài ạ?)\n\n- Anh/chị muốn làm công việc gì ạ?"
    offset = _next_sendable_offset(raw, min_offset=10)
    # The '?' inside the parenthetical is not a boundary; the cut lands right
    # after the ')' that closes it.
    assert raw[:offset].endswith("ạ?)\n")
    assert raw[offset:].startswith("\n- Anh/chị muốn làm công việc gì ạ?")


def test_compact_for_zalo_keeps_short_replies_untouched():
    from app.graph.progressive import compact_for_zalo

    short = "Dạ có ạ! VFIC đang tuyển nhiều việc phù hợp tại Hải Phòng ạ."
    assert compact_for_zalo(short) == short


def test_compact_for_zalo_cuts_long_replies_at_a_sentence_boundary():
    from app.graph.progressive import compact_for_zalo, _TRUNCATED_NOTE

    long = (
        "Dạ Amtran đang tuyển các vị trí tại KCN Vsip Thủy Nguyên:\n\n"
        "- Lắp ráp linh kiện điện tử: lương 6.3 triệu + phụ cấp 3-4 triệu/tháng\n"
        "- Kiểm tra chất lượng (QA): lương 6.3 triệu + phụ cấp 3-4 triệu/tháng\n"
        "- SMT (gắn linh kiện bằng máy tự động): lương 6.3 triệu + phụ cấp 3-4 triệu/tháng\n"
        "- MV: lương 6.3 triệu + phụ cấp 3-4 triệu/tháng\n\n"
        "Điểm nổi bật của Amtran:\n"
        "- Không yêu cầu bằng cấp, có hình xăm vẫn nhận\n"
        "- Được đào tạo chuyên môn từ đầu cho người chưa có kinh nghiệm\n\n"
        "Anh/chị có muốn tìm hiểu thêm về vị trí nào trong 4 vị trí trên không ạ? "
        "Nếu muốn em tư vấn chi tiết hơn nhé ạ!"
    )
    assert len(long) > 450

    compact = compact_for_zalo(long)

    assert len(compact) <= 450
    # The cut is a trimmed excerpt of the source: complete lines only, never a
    # mid-word fragment, and it carries the truncated-note for the candidate.
    assert compact.removesuffix(_TRUNCATED_NOTE).strip() in long
    assert compact.count("(") == compact.count(")")
    # Never cuts inside the parenthetical or a multi-million amount.
    assert compact.count("(") == compact.count(")")
    assert "6.3" in compact


def test_compact_for_zalo_never_cuts_mid_word():
    from app.graph.progressive import compact_for_zalo

    text = "Từ" + "kwxyz" * 200  # no sentence boundary anywhere inside the budget
    compact = compact_for_zalo(text)
    assert compact.startswith("Từ")
    assert text.startswith(compact)
