"""Webhook edge-case tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import hashlib
import json
from types import SimpleNamespace

import pytest


class FakeRequest:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_bot_webhook_dispatches_turn_through_rq(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(bot_webhook_secret="", bot_token="bot-token")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    handle = AsyncMock(return_value={"status": "start_failed"})
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)

    response = await webhooks.zalo_webhook(
        FakeRequest(json.dumps({"message": {"text": "Xin chào"}}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 503
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_run


@pytest.mark.asyncio
async def test_oa_webhook_dispatches_turn_through_rq(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(oa_secret_key="")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    handle = AsyncMock(return_value={"status": "start_failed"})
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)

    response = await webhooks.zalo_oa_webhook(
        FakeRequest(json.dumps({"event_name": "user_send_text"}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 503
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_run


@pytest.mark.asyncio
async def test_oa_webhook_accepts_unsigned_empty_registration_probe(monkeypatch):
    from app.api import webhooks

    settings_service = MagicMock()
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", settings_service)
    handle = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)

    response = await webhooks.zalo_oa_webhook(FakeRequest(b"{}"), db=AsyncMock())

    assert response.status_code == 200
    assert response.body == b'{"status":"verified"}'
    settings_service.assert_not_called()
    handle.assert_not_called()


@pytest.mark.asyncio
async def test_oa_webhook_temporarily_processes_unsigned_real_event(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(oa_secret_key="oa-secret", oa_app_id="app-1")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    handle = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)
    raw = json.dumps(
        {
            "event_name": "user_send_text",
            "timestamp": "1700000000",
            "sender": {"id": "user-1"},
            "message": {"msg_id": "msg-1", "text": "Xin chào"},
        }
    ).encode()

    response = await webhooks.zalo_oa_webhook(FakeRequest(raw), db=AsyncMock())

    assert response.status_code == 200
    handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_zalo_webhook_returns_400_for_malformed_json():
    from app.api.webhooks import zalo_webhook

    with patch("app.api.webhooks.ZaloWebhookService.handle", new_callable=AsyncMock) as handle:
        response = await zalo_webhook(FakeRequest(b"{not-json"), db=AsyncMock())

    assert response.status_code == 400
    handle.assert_not_called()


@pytest.mark.asyncio
async def test_failed_rq_enqueue_releases_webhook_lock(monkeypatch):
    import uuid

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    service = MagicMock()
    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = AsyncMock()
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=True)
    service.acquire_lock = AsyncMock(return_value=lock_owner)
    service.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-1",
                "chat": {"id": "bot-user-1"},
                "text": "Xin chào",
            }
        },
        enqueue=lambda _job: False,
    )

    assert result == {"status": "start_failed", "conversation_id": str(conv.id)}
    service.release_lock.assert_awaited_once_with(conv, lock_owner=lock_owner)


def test_zalo_oa_signature_verifier_accepts_documented_digest():
    from app.services.zalo_oa_signature import verify_signature

    payload = {
        "app_id": "app-1",
        "timestamp": "1700000000",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"app-1" + raw + b"1700000000" + b"secret").hexdigest()

    assert verify_signature(
        signature=f"sha256={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
    ).verified


def test_zalo_oa_signature_uses_timestamp_header_not_body():
    """Zalo signs with the X-ZEvent-Timestamp HEADER value, not the body field.

    Regression: the verifier used to read the body timestamp and permanently
    returned 401 because the header and body timestamps need not be equal.
    """
    from app.services.zalo_oa_signature import verify_signature

    payload = {
        "app_id": "app-1",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
        "timestamp": "body-ts-not-used",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header_ts = "1700000000000"
    digest = hashlib.sha256(b"app-1" + raw + header_ts.encode() + b"secret").hexdigest()

    assert verify_signature(
        signature=f"mac={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
        timestamp_header=header_ts,
    ).verified


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


@pytest.mark.asyncio
async def test_oa_user_seen_message_advances_delivery_to_read(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.apply_delivery_receipt = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    payload = {
        "event_name": "user_seen_message",
        "sender": {"id": "user-123"},
        "message": {"msg_id": "oa-msg-1"},
    }
    result = await ZaloWebhookService.handle(
        MagicMock(), payload, enqueue=lambda _j: True, channel="oa"
    )

    assert result == {"status": "receipt"}
    svc.ensure.assert_awaited_once_with("oa:user-123", zalo_channel="oa")
    svc.apply_delivery_receipt.assert_awaited_once()
    kwargs = svc.apply_delivery_receipt.call_args.kwargs
    assert kwargs["zalo_message_id"] == "oa-msg-1"
    assert kwargs["seen"] is True
    assert kwargs["delivered"] is False


@pytest.mark.asyncio
async def test_oa_user_received_message_advances_to_delivered(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.apply_delivery_receipt = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    payload = {
        "event_name": "user_received_message",
        "sender": {"id": "user-123"},
        "message": {"msg_id": "oa-msg-1"},
    }
    result = await ZaloWebhookService.handle(
        MagicMock(), payload, enqueue=lambda _j: True, channel="oa"
    )

    assert result == {"status": "receipt"}
    kwargs = svc.apply_delivery_receipt.call_args.kwargs
    assert kwargs["delivered"] is True
    assert kwargs["seen"] is False


@pytest.mark.asyncio
async def test_oa_follow_ensures_and_applies_follow(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.apply_follow = AsyncMock(return_value=conv)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {"event_name": "follow", "sender": {"id": "user-123"}},
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "follow"}
    svc.ensure.assert_awaited_once_with("oa:user-123", zalo_channel="oa")
    svc.apply_follow.assert_awaited_once_with(conv)
    svc.apply_unfollow.assert_not_called()


@pytest.mark.asyncio
async def test_oa_unfollow_opted_out_and_records_system_note(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.apply_unfollow = AsyncMock(return_value=conv)
    svc.record_system_note = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {"event_name": "unfollow", "sender": {"id": "user-123"}},
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "unfollow"}
    svc.apply_unfollow.assert_awaited_once_with(conv)
    svc.record_system_note.assert_awaited_once()
    assert "unfollow" in svc.record_system_note.call_args.kwargs["body"].lower()


@pytest.mark.asyncio
async def test_oa_button_click_records_system_note(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.record_system_note = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {
            "event_name": "user_click_button",
            "sender": {"id": "user-123"},
            "message": {"title": "Xem chi tiết"},
        },
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "button_click"}
    body = svc.record_system_note.call_args.kwargs["body"]
    assert "Xem chi tiết" in body


@pytest.mark.asyncio
async def test_oa_media_event_returns_ignored_without_db_write(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    svc = MagicMock()
    svc.ensure = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {
            "event_name": "user_send_image",
            "sender": {"id": "user-123"},
            "message": {"msg_id": "oa-msg-1"},
        },
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "ignored"}
    svc.ensure.assert_not_called()


@pytest.mark.asyncio
async def test_oa_text_message_starts_bot_turn(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="oa:user-123",
        zalo_channel="oa",
        version=1,
        mode="BOT",
    )
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.record_inbound = AsyncMock()
    svc.get = AsyncMock(return_value=conv)
    svc.run_start_guard = MagicMock(return_value=True)
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    svc.acquire_lock = AsyncMock(return_value=lock_owner)
    svc.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )

    db = MagicMock()
    db.refresh = AsyncMock()
    enqueued: list[dict] = []

    async def enqueue(job):
        enqueued.append(job)
        return True

    result = await ZaloWebhookService.handle(
        db,
        {
            "event_name": "user_send_text",
            "sender": {"id": "user-123", "name": "An"},
            "message": {"text": "Xin chào", "msg_id": "oa-msg-1"},
        },
        enqueue=enqueue,
        channel="oa",
    )

    assert result["status"] == "processing"
    assert len(enqueued) == 1
    assert enqueued[0]["user_text"] == "Xin chào"
    assert enqueued[0]["lock_owner"] == str(lock_owner)
    assert enqueued[0]["execution_source"] == "queued"
