"""Unit tests for the markdown → plain-text flattener.

Zalo renders outbound text verbatim, so the channel-agnostic agent reply is
flattened at the sender boundary. These pin the transformations and the things
that must survive untouched (URLs, snake_case identifiers, plain text).
"""

from __future__ import annotations

from app.shared.domain.text import plain_text


def test_plain_text_is_idempotent_on_plain_input():
    assert plain_text("Chào anh/chị, mật khẩu mới là Vfic@123") == (
        "Chào anh/chị, mật khẩu mới là Vfic@123"
    )


def test_plain_text_drops_emphasis_markup():
    assert plain_text("**đặt lại mật khẩu** chỉ hỗ trợ trên *Zalo OA*") == (
        "đặt lại mật khẩu chỉ hỗ trợ trên Zalo OA"
    )
    assert plain_text("__nghiêm trọng__ và ~~đã hết hạn~~") == (
        "nghiêm trọng và đã hết hạn"
    )
    assert plain_text("`reset_tingting_password`") == "reset_tingting_password"


def test_plain_text_keeps_link_targets_as_bare_text():
    reply = "Hỗ trợ tại [Zalo OA TingTing](https://zalo.me/3383849659955472174)"
    assert plain_text(reply) == (
        "Hỗ trợ tại Zalo OA TingTing: https://zalo.me/3383849659955472174"
    )
    # Bare and self-referencing links collapse to the URL alone.
    assert plain_text("[https://zalo.me/x](https://zalo.me/x)") == "https://zalo.me/x"


def test_plain_text_survives_snake_case_identifiers():
    # Underscore emphasis must never eat tool names or Python-ish words.
    assert plain_text("gọi reset_tingting_password sau khi xác thực") == (
        "gọi reset_tingting_password sau khi xác thực"
    )


def test_plain_text_normalizes_block_structure():
    md = "### Liên hệ\n\n> Ghi chú\n- bước một\n* bước hai\n\n\n\n---\nKết thúc"
    assert plain_text(md) == "Liên hệ\n\nGhi chú\n- bước một\n- bước hai\n\nKết thúc"
