"""Turn pairing for the Messenger extraction backfill.

The backfill re-runs history through the live persistence job, so a wrong
pairing silently writes one candidate's words under another candidate's turn.
These tests pin the pairing rule: each candidate message pairs with the next bot
reply, and a message with no reply after it is skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.conversation import MessageSender
from scripts.backfill_messenger_candidates import (
    EligibleConversation,
    TurnPair,
    _turn_pairs,
)

W = MessageSender.WORKER
B = MessageSender.BOT
S = MessageSender.SYSTEM


def pairs(messages: list[tuple[MessageSender, str]]):
    return [(p.user_text, p.bot_output) for p in _turn_pairs(messages)[0]]


def test_each_candidate_message_pairs_with_the_next_bot_reply():
    assert pairs(
        [
            (W, "0566866899"),
            (B, "Anh/chị cho em xin tên ạ"),
            (W, "Hoàng sóng"),
            (B, "Em ghi nhận tên Hoàng Sóng rồi ạ"),
        ]
    ) == [
        ("0566866899", "Anh/chị cho em xin tên ạ"),
        ("Hoàng sóng", "Em ghi nhận tên Hoàng Sóng rồi ạ"),
    ]


def test_a_trailing_candidate_message_with_no_reply_is_skipped():
    found, skipped_no_bot, skipped_blank = _turn_pairs(
        [(W, "0566866899"), (B, "Cho em xin tên ạ"), (W, "Hoàng sóng")]
    )
    assert [(p.user_text, p.bot_output) for p in found] == [("0566866899", "Cho em xin tên ạ")]
    assert skipped_no_bot == 1
    assert skipped_blank == 0


def test_two_adjacent_candidate_messages_keep_only_the_later_one():
    found, skipped_no_bot, _ = _turn_pairs([(W, "a"), (W, "b"), (B, "cảm ơn bạn")])
    assert [(p.user_text, p.bot_output) for p in found] == [("b", "cảm ơn bạn")]
    assert skipped_no_bot == 1


def test_unanswered_messages_are_kept_when_the_caller_asks_for_them():
    """The detail backfill mines the candidate's own words, reply or not.

    A message the bot never answered is where a phone number or a name most
    often arrives — production skipped 1262 such messages against 933 that had
    a reply — and the extraction reads ``user_text``, rendering an absent reply
    as empty.
    """
    found, skipped_no_bot, _ = _turn_pairs(
        [(W, "0566866899"), (B, "Cho em xin tên ạ"), (W, "Hoàng sóng"), (W, "0912345678")],
        include_unanswered=True,
    )
    assert [(p.user_text, p.bot_output) for p in found] == [
        ("0566866899", "Cho em xin tên ạ"),
        ("Hoàng sóng", ""),
        ("0912345678", ""),
    ]
    assert skipped_no_bot == 0


def test_unanswered_pairing_leaves_a_blank_body_alone():
    found, _, skipped_blank = _turn_pairs([(W, "   ")], include_unanswered=True)
    assert found == []
    assert skipped_blank == 1


def test_a_blank_candidate_message_is_not_a_turn():
    found, skipped_no_bot, skipped_blank = _turn_pairs([(W, "   "), (B, "chào bạn")])
    assert found == []
    assert skipped_blank == 1
    assert skipped_no_bot == 0


def test_system_chrome_never_ends_a_turn():
    found, _, _ = _turn_pairs(
        [(W, "0566866899"), (S, "bot đang trả lời"), (B, "Anh/chị cho em xin tên ạ")]
    )
    assert [(p.user_text, p.bot_output) for p in found] == [
        ("0566866899", "Anh/chị cho em xin tên ạ")
    ]


def test_a_bot_turn_is_taken_from_the_reply_immediately_after_the_candidate():
    """A second bot message (e.g. a follow-up nudge) must not be the reply."""
    found, _, _ = _turn_pairs(
        [
            (W, "Mình ở nam am Vĩnh bảo"),
            (B, "Dạ em ghi nhận anh/chị ở Nam Am, Vĩnh Bảo ạ."),
            (B, "Tin vui: tuyến xe LG Display có qua khỏi Nam Am."),
        ]
    )
    assert [(p.user_text, p.bot_output) for p in found] == [
        (
            "Mình ở nam am Vĩnh bảo",
            "Dạ em ghi nhận anh/chị ở Nam Am, Vĩnh Bảo ạ.",
        )
    ]


def test_the_enqueued_job_carries_the_keys_the_contact_keyed_write_needs():
    """chat_id stays the PSID; contact_id is what addresses the lead row."""
    import uuid

    from scripts.backfill_messenger_candidates import _enqueue

    captured: list[tuple[str, dict]] = []

    class _FakeRedis:
        pass

    conversation = EligibleConversation(
        conversation_id=uuid.UUID("c71b264b-82be-4111-9b84-cf2b84dd395e"),
        contact_id=uuid.UUID("ad5389c2-1e50-4878-9042-1c6c3a063d9a"),
        psid="28225543490450146",
    )
    pair = TurnPair(user_text="Hoàng sóng", bot_output="Dạ em ghi nhận rồi ạ")

    import app.workers.utils as worker_utils

    original = worker_utils.enqueue_job

    def _capture(queue, func, job):
        captured.append((queue, job))
        return True

    worker_utils.enqueue_job = _capture
    try:
        assert _enqueue(pair, conversation) is True
    finally:
        worker_utils.enqueue_job = original

    queue, job = captured[0]
    assert queue == "persistence_low"
    assert job["chat_id"] == "28225543490450146"
    assert job["contact_id"] == "ad5389c2-1e50-4878-9042-1c6c3a063d9a"
    assert job["conversation_id"] == "c71b264b-82be-4111-9b84-cf2b84dd395e"
    assert job["conversation_version"] is None
    assert job["user_text"] == "Hoàng sóng"
    assert job["bot_output"] == "Dạ em ghi nhận rồi ạ"
