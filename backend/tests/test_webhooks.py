"""Webhook edge-case tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest


def _runtime_authority():
    from app.services.installation.authority import RuntimeAuthorityFingerprint

    return RuntimeAuthorityFingerprint(
        authority_generation=1,
        revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        manifest_checksum="a" * 64,
        pack_contract_hash="b" * 64,
        persona_checksum="c" * 64,
        workflow_policy_checksum="d" * 64,
        provider_policy_checksum="e" * 64,
        authentication_policy_checksum="f" * 64,
        template_checksums={},
        active_kb_vector=(),
    ).stamp()


class FakeRequest:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_webhook_logs_never_include_candidate_body_or_signature(monkeypatch, caplog):
    from app.api import webhooks

    candidate_text = "Tôi tên Nguyễn Văn Bí Mật"
    signature = "sha256=super-secret-signature"
    raw = json.dumps(
        {
            "event_name": candidate_text,
            "app_id": "app-1",
            "timestamp": "1700000000",
            "message": {"text": candidate_text},
        }
    ).encode()
    cfg = SimpleNamespace(oa_secret_key="oa-secret", oa_app_id="app-1")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", AsyncMock(return_value={"status": "ignored"}))
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=None))

    with caplog.at_level("INFO", logger="app.api.webhooks"):
        response = await webhooks.zalo_oa_webhook(
            FakeRequest(raw, headers={"x-zevent-signature": signature}),
            db=AsyncMock(),
        )

    assert response.status_code == 200
    assert candidate_text not in caplog.text
    assert signature not in caplog.text
    assert "1700000000" not in caplog.text
    assert "bytes=" in caplog.text


@pytest.mark.asyncio
async def test_bot_webhook_dispatches_turn_through_rq(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(bot_webhook_secret="", bot_token="bot-token")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    handle = AsyncMock(return_value={"status": "start_failed"})
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

    response = await webhooks.zalo_webhook(
        FakeRequest(json.dumps({"message": {"text": "Xin chào"}}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 503
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_run
    assert handle.await_args.kwargs["runtime_authority"] == _runtime_authority()


@pytest.mark.asyncio
async def test_oa_webhook_dispatches_turn_through_rq(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(oa_secret_key="")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    handle = AsyncMock(return_value={"status": "start_failed"})
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

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
async def test_oa_webhook_processes_real_event_without_signature_check(monkeypatch, caplog):
    """Inbound OA signature verification is retired: a real event with no/invalid
    x-zevent-signature is processed normally (200, dispatched) with NO signature
    warning logged and NO health recording. A configured secret no longer triggers
    any verification path."""
    from app.api import webhooks

    cfg = SimpleNamespace(oa_secret_key="oa-secret", oa_app_id="app-1")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    handle = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))
    raw = json.dumps(
        {
            "event_name": "user_send_text",
            "timestamp": "1700000000",
            "sender": {"id": "user-1"},
            "message": {"msg_id": "msg-1", "text": "Xin chào"},
        }
    ).encode()

    with caplog.at_level("WARNING", logger="app.api.webhooks"):
        response = await webhooks.zalo_oa_webhook(FakeRequest(raw), db=AsyncMock())

    assert response.status_code == 200
    handle.assert_awaited_once()
    assert "event_class=oa_event" not in caplog.text
    assert "verification_failed" not in caplog.text


@pytest.mark.asyncio
async def test_oa_webhook_dispatches_verifiably_signed_event(monkeypatch):
    from app.api import webhooks
    from app.services.zalo_oa_signature import compute_mac

    app_id, secret, ts = "app-1", "oa-secret", "1700000000"
    raw = json.dumps(
        {
            "event_name": "user_send_text",
            "app_id": app_id,
            "timestamp": ts,
            "sender": {"id": "user-1"},
            "message": {"msg_id": "msg-1", "text": "Xin chào"},
        }
    ).encode()
    digest = compute_mac(app_id, raw.decode("utf-8"), ts, secret)

    cfg = SimpleNamespace(oa_secret_key=secret, oa_app_id=app_id)
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    handle = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

    req = FakeRequest(
        raw,
        headers={"x-zevent-signature": f"sha256={digest}", "x-zevent-timestamp": ts},
    )
    response = await webhooks.zalo_oa_webhook(req, db=AsyncMock())

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
async def test_verified_webhook_dispatches_without_runtime_authority(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(bot_webhook_secret="", bot_token="bot-token")
    monkeypatch.setattr(
        webhooks,
        "IntegrationSettingsService",
        lambda _db: SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg)),
    )
    inactive = AsyncMock(return_value=None)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", inactive)
    handle = AsyncMock(return_value={"status": "processing"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)

    response = await webhooks.zalo_webhook(
        FakeRequest(json.dumps({"message": {"text": "Xin chào"}}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 200
    assert response.body == b'{"status":"processing"}'
    inactive.assert_awaited_once()
    handle.assert_awaited_once()
    assert handle.await_args.kwargs["runtime_authority"] is None


@pytest.mark.asyncio
async def test_oa_webhook_dispatches_without_runtime_authority(monkeypatch):
    from app.api import webhooks

    cfg = SimpleNamespace(oa_secret_key="")
    monkeypatch.setattr(
        webhooks,
        "IntegrationSettingsService",
        lambda _db: SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg)),
    )
    inactive = AsyncMock(return_value=None)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", inactive)
    handle = AsyncMock(return_value={"status": "processing"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handle)

    response = await webhooks.zalo_oa_webhook(
        FakeRequest(json.dumps({"event_name": "user_send_text"}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 200
    assert response.body == b'{"status":"processing"}'
    inactive.assert_awaited_once()
    handle.assert_awaited_once()
    assert handle.await_args.kwargs["runtime_authority"] is None


@pytest.mark.asyncio
async def test_webhook_copies_active_runtime_authority_to_inbound_and_queued_turn(monkeypatch):
    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=3,
        mode="BOT",
    )
    service = MagicMock()
    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = AsyncMock()
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=True)
    service.acquire_lock = AsyncMock(return_value=uuid.UUID("00000000-0000-0000-0000-000000000002"))
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
        AsyncMock(return_value=None),
    )
    db = MagicMock()
    db.refresh = AsyncMock()
    jobs: list[dict] = []
    authority = _runtime_authority()

    result = await ZaloWebhookService.handle(
        db,
        {"message": {"message_id": "msg-1", "chat": {"id": "bot-user-1"}, "text": "Xin chào"}},
        enqueue=lambda job: jobs.append(job) or True,
        runtime_authority=authority,
    )

    assert result == {"status": "processing", "conversation_id": str(conv.id)}
    assert service.record_inbound.await_args.kwargs["runtime_revision_id"] == authority.revision_id
    assert service.record_inbound.await_args.kwargs["authority_generation"] == 1
    assert service.record_inbound.await_args.kwargs["runtime_fingerprint"] == authority.fingerprint
    assert jobs[0]["runtime_revision_id"] == str(authority.revision_id)
    assert jobs[0]["authority_generation"] == 1
    assert jobs[0]["runtime_fingerprint"] == authority.fingerprint


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


@pytest.mark.asyncio
async def test_webhook_persists_explicit_name_before_queuing_turn(monkeypatch):
    import uuid

    from app.services.webhook import ZaloWebhookService

    events: list[str] = []
    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    service = MagicMock()

    async def record_inbound(*_args, **_kwargs):
        events.append("inbound")

    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = record_inbound
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=True)
    service.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )

    async def persist_name(*_args, **_kwargs):
        events.append("profile")
        return "LiteQA"

    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
        persist_name,
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    def enqueue(_job):
        events.append("enqueue")
        return True

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-1",
                "chat": {"id": "bot-user-1"},
                "text": "mình tên LiteQA",
            }
        },
        enqueue=enqueue,
    )

    assert result == {"status": "processing", "conversation_id": str(conv.id)}
    assert events == ["inbound", "profile", "enqueue"]


@pytest.mark.asyncio
async def test_future_human_review_inbound_is_stored_without_extraction_or_bot(monkeypatch):
    import uuid

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        mode="HUMAN",
        needs_human=True,
    )
    service = MagicMock()
    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = AsyncMock()
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=False)
    service.acquire_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    persist_name = AsyncMock()
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
        persist_name,
    )
    db = MagicMock(refresh=AsyncMock())
    enqueue = MagicMock()

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-after-review",
                "chat": {"id": "bot-user-1"},
                "text": "Tin nhắn tiếp theo",
            }
        },
        enqueue=enqueue,
    )

    assert result == {"status": "starved_human_mode", "conversation_id": str(conv.id)}
    service.record_inbound.assert_awaited_once()
    persist_name.assert_not_awaited()
    service.acquire_lock.assert_not_awaited()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_active_semi_auto_still_captures_name_before_bot_guard(monkeypatch):
    import uuid

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        mode="SEMI_AUTO",
    )
    service = MagicMock()
    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = AsyncMock()
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=False)
    service.acquire_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    persist_name = AsyncMock(return_value="An")
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
        persist_name,
    )
    db = MagicMock(refresh=AsyncMock())
    enqueue = MagicMock()

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-semi-auto",
                "chat": {"id": "bot-user-1"},
                "text": "Mình tên An",
            }
        },
        enqueue=enqueue,
    )

    assert result == {"status": "starved_human_mode", "conversation_id": str(conv.id)}
    persist_name.assert_awaited_once()
    service.acquire_lock.assert_not_awaited()
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_rolls_back_profile_failure_then_queues_turn(monkeypatch, caplog):
    import uuid

    from app.services.webhook import ZaloWebhookService

    events: list[str] = []
    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    service = MagicMock()

    async def record_inbound(*_args, **_kwargs):
        events.append("inbound")

    service.ensure = AsyncMock(return_value=conv)
    service.record_inbound = record_inbound
    service.get = AsyncMock(return_value=conv)
    service.run_start_guard = MagicMock(return_value=True)
    service.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )

    async def persist_name(*_args, **_kwargs):
        events.append("profile")
        raise RuntimeError("LiteQA confidential detail")

    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_name",
        persist_name,
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    async def rollback():
        events.append("rollback")

    db.rollback = rollback

    def enqueue(_job):
        events.append("enqueue")
        return True

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-1",
                "chat": {"id": "bot-user-1"},
                "text": "mình tên LiteQA",
            }
        },
        enqueue=enqueue,
    )

    assert result == {"status": "processing", "conversation_id": str(conv.id)}
    assert events == ["inbound", "profile", "rollback", "enqueue"]
    assert "LiteQA" not in caplog.text


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
    svc.apply_delivery_receipt_batch = AsyncMock(return_value=1)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    # user_seen_message carries msg_ids as an ARRAY (a user sees several messages
    # at once). Sender is the OA, recipient is the user (inverted from text).
    payload = {
        "event_name": "user_seen_message",
        "sender": {"id": "oa-1"},
        "recipient": {"id": "user-123"},
        "message": {"msg_ids": ["oa-msg-1", "oa-msg-2"]},
    }
    result = await ZaloWebhookService.handle(
        MagicMock(), payload, enqueue=lambda _j: True, channel="oa"
    )

    assert result == {"status": "receipt"}
    # Receipts scope to the recipient (the user), not the sender (the OA).
    svc.ensure.assert_awaited_once_with("oa:user-123", zalo_channel="oa")
    svc.apply_delivery_receipt_batch.assert_awaited_once()
    kwargs = svc.apply_delivery_receipt_batch.call_args.kwargs
    # Every id in the batch is forwarded so all matched messages advance to READ.
    assert kwargs["zalo_message_ids"] == ["oa-msg-1", "oa-msg-2"]
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
    svc.apply_delivery_receipt_batch = AsyncMock(return_value=1)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    payload = {
        "event_name": "user_received_message",
        "sender": {"id": "oa-1"},
        "recipient": {"id": "user-123"},
        "message": {"msg_id": "oa-msg-1"},
    }
    result = await ZaloWebhookService.handle(
        MagicMock(), payload, enqueue=lambda _j: True, channel="oa"
    )

    assert result == {"status": "receipt"}
    kwargs = svc.apply_delivery_receipt_batch.call_args.kwargs
    assert kwargs["zalo_message_ids"] == ["oa-msg-1"]
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
        {"event_name": "follow", "follower": {"id": "user-123"}},
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
        {"event_name": "unfollow", "follower": {"id": "user-123"}},
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

    # Capture the best-effort OA profile enrichment enqueue (fire-and-forget on
    # the persistence_low queue). Mocked so the test never touches Redis.
    enrich_calls: list[dict] = []

    def _fake_enqueue_enrich(job):
        enrich_calls.append(job)

    monkeypatch.setattr(
        "app.workers.persistence_worker.enqueue_enrich_oa_profile",
        _fake_enqueue_enrich,
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
    # The OA profile enrichment job is enqueued fire-and-forget with the
    # conversation-scoped zalo_id and the external OA user id.
    assert len(enrich_calls) == 1
    assert enrich_calls[0] == {"zalo_id": "oa:user-123", "user_id": "user-123"}


# ─── Phase 1 characterization: Zalo behaviors the neutral contracts must
# preserve when Phase 3 wraps Bot/OA behind the channel-neutral ports.
#
# These tests freeze the shape and semantics — not the implementation — so a
# Phase 3 refactor can prove it preserves them. They are additive and do not
# change existing coverage.
# ────────────────────────────────────────────────────────────────────────────


def test_phase1_bot_normalizer_emits_five_field_shape():
    """The Bot normalizer emits exactly the fields the future neutral
    ChannelInboundMessage will be built from: chat_id, channel, text, name,
    msg_id (plus derived hash). Phase 3 wraps this; the shape must not drift.
    """
    from app.services.webhook import ZaloWebhookService

    norm = ZaloWebhookService.normalize_bot(
        {
            "message": {
                "message_id": 42,
                "text": "Ứng tuyển",
                "chat": {"id": "chat-1"},
                "from": {"id": 7, "name": "An"},
            }
        }
    )
    assert norm is not None
    # the five neutral-relevant fields
    assert norm.zalo_chat_id == "chat-1"
    assert norm.zalo_channel == "bot"
    assert norm.user_text == "Ứng tuyển"
    assert norm.user_name == "An"
    assert norm.msg_id == "42"
    # deterministic dedup hash derived from msg_id (the durable idempotency key)
    assert norm.msg_hash == hashlib.sha256(b"42").hexdigest()[:32]


def test_phase1_bot_normalizer_rejects_non_text_without_side_effect():
    """Non-text events (media, location, sticker) must not produce a
    NormalizedMessage — the Phase 5 Messenger edge mirrors this rule.
    """
    from app.services.webhook import ZaloWebhookService

    # no text
    assert (
        ZaloWebhookService.normalize_bot(
            {"message": {"chat": {"id": "c"}, "photo": "x"}}
        )
        is None
    )
    # no chat id
    assert (
        ZaloWebhookService.normalize_bot({"message": {"text": "hi"}}) is None
    )


def test_phase1_oa_scoped_chat_id_prefix_is_the_account_boundary():
    """OA external ids are namespaced as ``oa:<user_id>`` — this prefix is the
    seed for the neutral account-scoped identity (account_key separates the OA
    account from the Bot account even before Phase 2 backfill). Phase 3 must
    preserve this prefix behavior in the OA normalizer wrapper.
    """
    from app.services.webhook import ZaloWebhookService

    norm = ZaloWebhookService.normalize_oa(
        {
            "event_name": "user_send_text",
            "sender": {"id": "user-9", "name": "Bình"},
            "message": {"text": "hello", "msg_id": "m9"},
        }
    )
    assert norm is not None
    assert norm.zalo_chat_id == "oa:user-9"
    assert norm.zalo_channel == "oa"


def test_phase1_channel_string_is_bot_or_oa_only():
    """The two Zalo provider/channel strings that Phase 3 will register as
    neutral provider ids. A third value must never appear from the normalizers.
    """
    from app.services.webhook import ZaloWebhookService

    bot = ZaloWebhookService.normalize_bot(
        {"message": {"text": "x", "chat": {"id": "c"}, "message_id": 1}}
    )
    oa = ZaloWebhookService.normalize_oa(
        {
            "event_name": "user_send_text",
            "sender": {"id": "u"},
            "message": {"text": "x", "msg_id": "m"},
        }
    )
    assert bot.zalo_channel == "bot"
    assert oa.zalo_channel == "oa"
    assert {bot.zalo_channel, oa.zalo_channel} == {"bot", "oa"}


def test_phase1_typing_difference_bot_fires_oa_does_not():
    """Bot has a typing endpoint; OA does not. The neutral capability contract
    (TypingCapability) must preserve this: the Bot wrapper will implement it,
    the OA wrapper will not. This test freezes the *source* of that difference
    by asserting the typing call site is *structurally nested* inside an
    ``if norm.zalo_channel == "bot"`` guard — not merely textually after it.
    """
    import ast
    import inspect
    import textwrap

    from app.services.webhook import ZaloWebhookService

    src = textwrap.dedent(inspect.getsource(ZaloWebhookService.handle))
    tree = ast.parse(src)

    # Walk with parent tracking so we can assert structural dominance, not
    # just textual ordering. A bare line-order check would pass even if the
    # call were moved into an unrelated later branch.
    parent_map: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[id(child)] = parent

    typing_calls = [
        n
        for n in ast.walk(tree)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_fire_typing"
        )
    ]
    assert len(typing_calls) == 1, "exactly one _fire_typing call site in handle()"
    call = typing_calls[0]

    # Walk up the parent chain; the nearest enclosing If must test
    # `norm.zalo_channel == "bot"` (or the reverse). This is the real gate.
    def _is_bot_channel_test(node: ast.AST) -> bool:
        if not isinstance(node, ast.If):
            return False
        test = node.test
        # match `X == "bot"` or `"bot" == X`
        if not isinstance(test, ast.Compare):
            return False
        if not (test.ops and isinstance(test.ops[0], ast.Eq)):
            return False
        for operand in (test.left, *test.comparators):
            if isinstance(operand, ast.Constant) and operand.value == "bot":
                return True
        return False

    node: ast.AST = call
    found_gate = False
    while id(node) in parent_map:
        parent = parent_map[id(node)]
        if _is_bot_channel_test(parent):
            found_gate = True
            break
        node = parent
    assert found_gate, (
        "_fire_typing call must be nested inside an "
        "`if norm.zalo_channel == \"bot\"` guard (OA has no typing endpoint)"
    )


# ─── Phase 1 characterization: send-error classification taxonomy ────────────
#
# The neutral ChannelSendResult reuses the existing error_class taxonomy from
# app.graph.send_classification. These tests freeze that mapping so Phase 3's
# adapter wrappers and Phase 5's Messenger adapter cannot drift it.


def test_phase1_ambiguous_transport_classes_map_to_send_unknown():
    """The conservative classifier: any failure that MAY have reached the
    provider after the request was written is non-retriable SEND_UNKNOWN.
    """
    from app.graph.send_classification import (
        AMBIGUOUS_SEND_CLASSES,
        delivery_status_for_send_error,
    )
    from app.models.conversation import DeliveryStatus

    for cls in AMBIGUOUS_SEND_CLASSES:
        assert (
            delivery_status_for_send_error(cls, ok=False) is DeliveryStatus.SEND_UNKNOWN
        ), f"{cls} should map to SEND_UNKNOWN"


def test_phase1_connect_error_is_retryable_failed_not_send_unknown():
    """A definite pre-send connection failure is retryable FAILED, not
    terminal SEND_UNKNOWN. Phase 3/5 adapters must preserve this distinction.
    """
    from app.graph.send_classification import delivery_status_for_send_error

    assert delivery_status_for_send_error("connect_error", ok=False) is None
    # None → caller falls back to default FAILED (retryable)


def test_phase1_send_classification_is_provider_neutral():
    """The taxonomy module's executable code imports no provider module and
    branches on no provider id — the proof that the SEND_UNKNOWN decision
    does not branch on Zalo vs Facebook. Docstrings may mention Zalo as
    historical context; the *code* must not.
    """
    import ast
    import inspect

    from app.graph import send_classification

    src = inspect.getsource(send_classification)
    # Strip docstrings and comments by parsing to AST and back, leaving only
    # executable code. Provider names in prose are acceptable; in code they are not.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")  # strip docstring
    code_only = ast.unparse(tree)
    lowered = code_only.lower()
    assert "zalo" not in lowered
    assert "facebook" not in lowered
    assert "messenger" not in lowered


# ─── Phase 3: no secrets in the RQ payload ───────────────────────────────────


@pytest.mark.asyncio
async def test_phase3_queued_job_carries_no_provider_token(monkeypatch):
    """The v2 webhook payload must NOT carry zalo_bot_token (or any provider
    token). The worker resolves credentials fresh from DB. A secret in the RQ
    payload is a secret in Redis — Phase 3 closes that hole.

    Regression guard: an earlier payload carried the live DB-resolved Bot token
    so the typing-bridge pulse would work when env ZALO_BOT_TOKEN was stale.
    The bridge now resolves the token worker-side.
    """
    from app.api import webhooks
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    enqueued: list[dict] = []

    def _capture(job):
        enqueued.append(job)
        return True

    cfg = SimpleNamespace(bot_webhook_secret="", bot_token="secret-bot-token-12345")
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(
        webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority())
    )
    # Stub handle to call the real enqueue-capture path through the router, but
    # the simplest proof is to invoke ZaloWebhookService.handle directly with the
    # real enqueue callback so we observe the exact payload.
    from app.services.webhook import ZaloWebhookService

    db = AsyncMock()
    # Minimal ensure/record_inbound/get stubs so handle() reaches the enqueue.
    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="chat-secret-test",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    svc = AsyncMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.get = AsyncMock(return_value=conv)
    svc.record_inbound = AsyncMock()
    svc.run_start_guard = lambda c: True
    svc.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    svc.release_lock = AsyncMock()
    # ConversationService + CandidateExtractionService + dedup are imported
    # inside handle() — patch the service module where they're looked up.
    import app.services.webhook as wh_mod
    from app.services import candidate_extraction as ce_mod

    monkeypatch.setattr(wh_mod, "ConversationService", lambda _db: svc)
    monkeypatch.setattr(ce_mod, "CandidateExtractionService", SimpleNamespace(
        persist_explicit_name=AsyncMock()
    ))
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )

    await ZaloWebhookService.handle(
        db,
        {"message": {"text": "hi", "chat": {"id": "chat-secret-test"}, "message_id": 1}},
        enqueue=_capture,
        channel="bot",
        bot_token="secret-bot-token-12345",
        runtime_authority=_runtime_authority(),
    )

    assert len(enqueued) == 1, "job was not enqueued"
    job = enqueued[0]
    assert "zalo_bot_token" not in job, (
        f"zalo_bot_token must not be carried in the v2 RQ payload; got keys: {sorted(job)}"
    )
    assert job.get("v") == 2
    # No value in the payload should look like the token.
    for key, value in job.items():
        assert value != "secret-bot-token-12345", (
            f"token-like value leaked via payload key {key!r}"
        )
