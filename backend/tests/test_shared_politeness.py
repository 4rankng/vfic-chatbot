"""Known-pleasantry lexicon — the ack lane's fail-closed backstop."""

from __future__ import annotations

import pytest

from app.shared.domain.politeness import is_known_pleasantry


@pytest.mark.parametrize(
    "text",
    [
        "hi",
        "XIN CHÀO",
        "Chào bạn!",
        "cảm ơn bạn nhe",
        "cam on anh nhiu",
        "thanks ban",
        "tạm biệt",
        "bye bye",
        "ok",
        "Ok ạ",
        "dạ",
        "Dạ đây ạ",
        "vâng",
        "da vâng",
        "được ạ",
        "hiểu rồi",
        "cam on nha",
        "😊",
        "👍",
        "😊😊",
        " ❤️ ",
    ],
)
def test_known_pleasantries_ack(text: str) -> None:
    assert is_known_pleasantry(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # The 2026-10-08 incident: a district answer to the bot's own question.
        "Đồng triều ạ",
        "dong trieu",
        "Hạ Long",
        # Bare numbers carry information (an age answer).
        "25",
        # Yes/no and content answers.
        "có",
        "không",
        "ok không biết luôn",
        "ok mà lương bao nhiêu",
        # Punctuation-only is a question attempt, not a pleasantry.
        "????",
        # Empty.
        "",
        None,
    ],
)
def test_content_answers_never_ack(text: str | None) -> None:
    assert is_known_pleasantry(text) is False
