"""OA webhook event classification — lifecycle + receipt kinds."""
from __future__ import annotations

from app.services.zalo_oa_events import parse_oa_webhook_event


def test_classify_follow_event():
    event = parse_oa_webhook_event({"event_name": "follow", "sender": {"id": "u1"}})
    assert event is not None
    assert event.kind == "follow"
    assert event.is_lifecycle is True
    assert event.can_start_bot_turn is False
    assert event.can_trigger_receipt is False


def test_classify_unfollow_event():
    event = parse_oa_webhook_event({"event_name": "unfollow", "sender": {"id": "u1"}})
    assert event is not None
    assert event.kind == "unfollow"
    assert event.is_lifecycle is True
    assert event.can_start_bot_turn is False


def test_user_seen_can_trigger_receipt():
    event = parse_oa_webhook_event(
        {
            "event_name": "user_seen_message",
            "sender": {"id": "u1"},
            "message": {"msg_id": "m1"},
        }
    )
    assert event.kind == "user_seen"
    assert event.can_trigger_receipt is True
    assert event.can_start_bot_turn is False
    assert event.is_lifecycle is False


def test_user_received_can_trigger_receipt():
    event = parse_oa_webhook_event(
        {
            "event_name": "user_received_message",
            "sender": {"id": "u1"},
            "message": {"msg_id": "m1"},
        }
    )
    assert event.kind == "user_received"
    assert event.can_trigger_receipt is True


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
