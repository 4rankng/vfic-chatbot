"""Webhook edge-case tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import hashlib
import json

import pytest


class FakeRequest:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_zalo_webhook_returns_400_for_malformed_json():
    from app.api.webhooks import zalo_webhook

    with patch("app.api.webhooks.ZaloWebhookService.handle", new_callable=AsyncMock) as handle:
        response = await zalo_webhook(FakeRequest(b"{not-json"), db=AsyncMock())

    assert response.status_code == 400
    handle.assert_not_called()


def test_zalo_oa_signature_verifier_accepts_documented_digest():
    from app.api.webhooks import _verify_oa_signature

    payload = {
        "app_id": "app-1",
        "timestamp": "1700000000",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"app-1" + raw + b"1700000000" + b"secret").hexdigest()

    assert _verify_oa_signature(
        signature=f"sha256={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
    )


def test_zalo_oa_normalizer_maps_text_message_to_scoped_chat_id():
    from app.services.webhook import ZaloWebhookService

    norm = ZaloWebhookService.normalize_oa(
        {
            "event_name": "user_send_text",
            "sender": {"id": "user-123", "name": "An"},
            "message": {"text": "Xin chào", "msg_id": "oa-msg-1"},
        }
    )

    assert norm is not None
    assert norm.zalo_channel == "oa"
    assert norm.zalo_chat_id == "oa:user-123"
    assert norm.user_text == "Xin chào"
    assert norm.user_name == "An"


def test_zalo_oa_event_parser_classifies_non_chat_events_without_bot_turn():
    from app.services.zalo_oa_events import parse_oa_webhook_event

    event = parse_oa_webhook_event(
        {
            "event_name": "user_seen_message",
            "sender": {"id": "user-123"},
            "recipient": {"id": "oa-1"},
            "message": {"msg_id": "oa-msg-1"},
        }
    )

    assert event is not None
    assert event.kind == "user_seen"
    assert event.sender_id == "user-123"
    assert event.message_id == "oa-msg-1"
    assert event.can_start_bot_turn is False


def test_zalo_oa_normalizer_ignores_delivery_and_status_events():
    from app.services.webhook import ZaloWebhookService

    assert (
        ZaloWebhookService.normalize_oa(
            {
                "event_name": "oa_send_text",
                "sender": {"id": "oa-1"},
                "recipient": {"id": "user-123"},
                "message": {"text": "Đã gửi", "msg_id": "oa-msg-1"},
            }
        )
        is None
    )
