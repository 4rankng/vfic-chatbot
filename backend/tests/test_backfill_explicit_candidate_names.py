"""Pins for the deterministic candidate-name backfill.

The bug these guard against: the inbound name capture looked back through
``last_messages`` (newest-first) with ``reversed(...)``, so the bot turn it
compared a bare reply against was usually not the name request — and the write
itself was Zalo-chat-id keyed, which a Messenger thread cannot satisfy. The
backfill replays the same extractor over stored history, so these two rules are
the whole safety story: only the immediately preceding bot turn counts, and the
candidate's own words must be unambiguous.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.webhook import _previous_bot_message
from scripts.backfill_explicit_candidate_names import name_from_history

# The real shape of the production thread this was written for. The stored
# inbound is lowercase ("Bùi thị hòa"); the console capitalises it for display.
_HISTORY: list[tuple[str, str]] = [
    ("WORKER", "Phải hc hoặc làm ca sáng thôi em"),
    ("BOT", "Dạ em hiểu rồi ạ, chị cần việc hành chính hoặc ca sáng để còn chăm con."),
    ("WORKER", "0395898185"),
    (
        "BOT",
        "Dạ em đã ghi nhận số điện thoại 0395898185 của chị rồi ạ 😊 "
        "Chị cho biết thêm chị tên gì để em ghi vào hồ sơ cho tiện liên hệ ạ?",
    ),
    ("WORKER", "Bùi thị hòa"),
]

_NAME_REQUEST = (
    "Dạ em đã ghi nhận số điện thoại 0395898185 của chị rồi ạ 😊 "
    "Chị cho biết thêm chị tên gì để em ghi vào hồ sơ cho tiện liên hệ ạ?"
)


def _turns(rows: list[tuple[str, str]]) -> list[SimpleNamespace]:
    """The ORM shape ``_previous_bot_message`` reads (``.sender`` / ``.body``)."""
    return [SimpleNamespace(sender=sender, body=body) for sender, body in rows]


def test_previous_bot_message_takes_the_immediate_predecessor():
    """``last_messages`` is newest-first, so the first bot row is the answer."""
    newest_first = list(reversed(_turns(_HISTORY)))

    assert _previous_bot_message(newest_first) == _NAME_REQUEST
    # The pre-fix iteration (reversed over a newest-first list) picked an older
    # bot turn, which matches no name request at all.
    assert (
        next((m.body for m in reversed(newest_first) if m.sender == "BOT"), "")
        != _previous_bot_message(newest_first)
    )


def test_previous_bot_message_is_none_without_a_bot_turn():
    assert _previous_bot_message(_turns([("WORKER", "Giang")])) is None
    assert _previous_bot_message([]) is None


def test_name_from_history_captures_a_bare_reply_to_the_name_request():
    assert name_from_history(_HISTORY) == "Bùi thị hòa"


def test_name_from_history_captures_an_explicit_introduction():
    assert (
        name_from_history(
            [
                ("BOT", "Dạ em chào anh/chị ạ."),
                ("WORKER", "mình tên Nguyễn Văn Dũng"),
            ]
        )
        == "Nguyễn Văn Dũng"
    )


def test_name_from_history_ignores_a_bare_reply_without_a_name_request():
    """A one-word turn after any other bot message is not a name."""
    assert (
        name_from_history(
            [
                ("BOT", "Anh/chị đang quan tâm dự án nào để em kiểm tra nhé?"),
                ("WORKER", "Giang"),
            ]
        )
        is None
    )


def test_name_from_history_ignores_answers_that_are_not_names():
    """The token after a name request is still rejected when it is not a name."""
    assert name_from_history([("BOT", "Chị cho em biết chị tên gì ạ?"), ("WORKER", "không có")]) is None
