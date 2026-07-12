"""OA webhook event classification — lifecycle + receipt kinds."""

from __future__ import annotations

from app.services.zalo_oa_events import parse_oa_webhook_event


def test_classify_follow_event():
    # Zalo identifies the user under ``follower`` for follow/unfollow, not ``sender``.
    event = parse_oa_webhook_event({"event_name": "follow", "follower": {"id": "u1"}})
    assert event is not None
    assert event.kind == "follow"
    assert event.is_lifecycle is True
    assert event.can_start_bot_turn is False
    assert event.can_trigger_receipt is False
    assert event.sender_id == "u1"
    assert event.scoped_chat_id == "oa:u1"


def test_classify_unfollow_event():
    event = parse_oa_webhook_event({"event_name": "unfollow", "follower": {"id": "u1"}})
    assert event is not None
    assert event.kind == "unfollow"
    assert event.is_lifecycle is True
    assert event.can_start_bot_turn is False
    assert event.sender_id == "u1"
    assert event.scoped_chat_id == "oa:u1"


def test_user_seen_can_trigger_receipt():
    # Zalo inverts sender/recipient for receipts: sender is the OA, recipient is
    # the user. The conversation must be scoped to the recipient (the user).
    # user_seen_message carries msg_ids as an ARRAY (a user can see several
    # messages at once) — every id must be preserved for batch delivery update.
    event = parse_oa_webhook_event(
        {
            "event_name": "user_seen_message",
            "sender": {"id": "OA_ID"},
            "recipient": {"id": "USER_ID"},
            "message": {"msg_ids": ["m1", "m2", "m2"]},
        }
    )
    assert event.kind == "user_seen"
    assert event.can_trigger_receipt is True
    assert event.can_start_bot_turn is False
    assert event.is_lifecycle is False
    assert event.sender_id == "OA_ID"
    assert event.recipient_id == "USER_ID"
    assert event.scoped_chat_id == "oa:USER_ID"
    # All ids captured, deduped, order preserved.
    assert event.message_ids == ("m1", "m2")
    assert event.message_id == ""  # no single msg_id in this payload


def test_user_received_can_trigger_receipt():
    # Same inverted sender/recipient as user_seen_message, but a single msg_id.
    event = parse_oa_webhook_event(
        {
            "event_name": "user_received_message",
            "sender": {"id": "OA_ID"},
            "recipient": {"id": "USER_ID"},
            "message": {"msg_id": "m1"},
        }
    )
    assert event.kind == "user_received"
    assert event.can_trigger_receipt is True
    assert event.sender_id == "OA_ID"
    assert event.recipient_id == "USER_ID"
    assert event.scoped_chat_id == "oa:USER_ID"
    # Single-id payload normalizes to a one-element tuple.
    assert event.message_ids == ("m1",)
    assert event.message_id == "m1"


def test_text_message_can_start_bot_turn():
    event = parse_oa_webhook_event(
        {
            "event_name": "user_send_text",
            "sender": {"id": "u1"},
            "message": {"text": "hi", "msg_id": "m1"},
        }
    )
    assert event.kind == "incoming_text"
    assert event.can_start_bot_turn is True
    assert event.can_trigger_receipt is False
    assert event.is_lifecycle is False
