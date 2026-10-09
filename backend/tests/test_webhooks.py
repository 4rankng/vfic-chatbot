"""Webhook edge-case tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    monkeypatch.setattr(
        webhooks,
        "run_zalo_ingress",
        AsyncMock(return_value={"status": "ignored"}),
    )
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
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

    response = await webhooks.zalo_webhook(
        FakeRequest(json.dumps({"message": {"text": "Xin chào"}}).encode()),
        db=AsyncMock(),
    )

    assert response.status_code == 503
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_turn_async
    assert handle.await_args.kwargs["runtime_authority"] == _runtime_authority()


@pytest.mark.asyncio
async def test_valid_oa_webhook_preserves_start_failed_retry_mapping(monkeypatch):
    from app.api import webhooks
    from app.services.zalo_oa_signature import compute_mac

    app_id, secret, ts = "app-1", "oa-secret", "1700000000"
    raw = json.dumps(
        {
            "event_name": "user_send_text",
            "app_id": app_id,
            "timestamp": ts,
        }
    ).encode()
    digest = compute_mac(app_id, raw.decode("utf-8"), ts, secret)
    cfg = SimpleNamespace(oa_secret_key=secret, oa_app_id=app_id)
    settings_service = SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg))
    handle = AsyncMock(return_value={"status": "start_failed"})
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", lambda _db: settings_service)
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

    response = await webhooks.zalo_oa_webhook(
        FakeRequest(
            raw,
            headers={"x-zevent-signature": f"sha256={digest}", "x-zevent-timestamp": ts},
        ),
        db=AsyncMock(),
    )

    assert response.status_code == 503
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_turn_async


@pytest.mark.asyncio
async def test_oa_webhook_accepts_unsigned_empty_registration_probe(monkeypatch):
    from app.api import webhooks

    settings_service = MagicMock()
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", settings_service)
    handle = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)

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
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)
    runtime_lookup = AsyncMock(return_value=_runtime_authority())
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", runtime_lookup)
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
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=_runtime_authority()))

    req = FakeRequest(
        raw,
        headers={"x-zevent-signature": f"sha256={digest}", "x-zevent-timestamp": ts},
    )
    response = await webhooks.zalo_oa_webhook(req, db=AsyncMock())

    assert response.status_code == 200
    handle.assert_awaited_once()
    assert handle.await_args.kwargs["enqueue"] is webhooks.enqueue_chat_turn_async
    assert handle.await_args.kwargs["runtime_authority"] == _runtime_authority()


@pytest.mark.asyncio
async def test_zalo_webhook_returns_400_for_malformed_json():
    from app.api.webhooks import zalo_webhook

    with patch("app.api.webhooks.run_zalo_ingress", new_callable=AsyncMock) as handle:
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
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)

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
    monkeypatch.setattr(webhooks, "run_zalo_ingress", handle)

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
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=uuid.UUID("00000000-0000-0000-0000-000000000002"))
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
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
    assert service.state.record_inbound.await_args.kwargs["runtime_revision_id"] == authority.revision_id
    assert service.state.record_inbound.await_args.kwargs["authority_generation"] == 1
    assert service.state.record_inbound.await_args.kwargs["runtime_fingerprint"] == authority.fingerprint
    assert jobs[0]["runtime_revision_id"] == str(authority.revision_id)
    assert jobs[0]["authority_generation"] == 1
    assert jobs[0]["runtime_fingerprint"] == authority.fingerprint


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_paused_page_persists_the_message_but_enqueues_no_turn(monkeypatch):
    """The owner pause switch receives data and sends nothing.

    2026-10-08: a paused Page must keep the full candidate thread (the message
    is persisted like any inbound) while no bot turn is enqueued — the thread
    waits for a human reply, and the reconcile sweep skips it too, so nothing
    "recovers" it into a bot reply later.
    """
    import uuid

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-paused-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    enqueued: list[dict] = []
    service = MagicMock()
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=True)
    service.state.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    service.state.release_lock = AsyncMock()

    import app.services.webhook as wh_mod

    monkeypatch.setattr(wh_mod, "ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    result = await ZaloWebhookService.handle(
        db,
        {"message": {"text": "con người ơi", "chat": {"id": "bot-paused-1"}, "message_id": 9}},
        enqueue=enqueued.append,
        channel="bot",
        bot_token="token",
    )

    assert result["status"] == "bot_paused"
    assert service.state.record_inbound.await_count == 1
    assert enqueued == []
    service.state.acquire_lock.assert_not_awaited()


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
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=lock_owner)
    service.state.release_lock = AsyncMock()
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
    service.state.release_lock.assert_awaited_once_with(conv, lock_owner=lock_owner)


@pytest.mark.asyncio
async def test_inbound_while_the_mutex_is_held_is_stored_but_not_queued(monkeypatch):
    """The ingress guard refuses a second inbound for a locked conversation.

    The message is durably stored — a later turn can still answer it, which is
    what the worker's newest-inbound hand-off relies on — but no job is enqueued
    for it: the turn holding the per-chat mutex is the only one that can hand the
    conversation over to it.
    """
    import uuid

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=2,
        mode="BOT",
    )
    service = MagicMock()
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=None)  # a turn is in flight
    service.state.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
        AsyncMock(return_value=None),
    )
    db = MagicMock()
    db.refresh = AsyncMock()
    enqueue = MagicMock()

    result = await ZaloWebhookService.handle(
        db,
        {
            "message": {
                "message_id": "msg-2",
                "chat": {"id": "bot-user-1"},
                "text": "Hello",
            }
        },
        enqueue=enqueue,
    )

    assert result == {"status": "locked", "conversation_id": str(conv.id)}
    service.state.record_inbound.assert_awaited_once()  # the message is not lost
    enqueue.assert_not_called()  # ...but it gets no turn of its own
    service.state.release_lock.assert_not_awaited()  # the in-flight turn still owns the lock


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

    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = record_inbound
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )

    async def persist_name(*_args, **_kwargs):
        events.append("profile")
        return "LiteQA"

    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
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
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=False)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    persist_name = AsyncMock()
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
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
    service.state.record_inbound.assert_awaited_once()
    persist_name.assert_not_awaited()
    service.state.acquire_lock.assert_not_awaited()
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
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=False)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    persist_name = AsyncMock(return_value="An")
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
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
    service.state.acquire_lock.assert_not_awaited()
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

    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = record_inbound
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )

    async def persist_name(*_args, **_kwargs):
        events.append("profile")
        raise RuntimeError("LiteQA confidential detail")

    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
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
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.apply_delivery_receipt_batch = AsyncMock(return_value=1)
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
    svc.state.ensure.assert_awaited_once_with(
        "oa:user-123", zalo_channel="oa", account_key=None
    )
    svc.state.apply_delivery_receipt_batch.assert_awaited_once()
    kwargs = svc.state.apply_delivery_receipt_batch.call_args.kwargs
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
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.apply_delivery_receipt_batch = AsyncMock(return_value=1)
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
    kwargs = svc.state.apply_delivery_receipt_batch.call_args.kwargs
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
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.apply_follow = AsyncMock(return_value=conv)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {"event_name": "follow", "follower": {"id": "user-123"}},
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "follow"}
    svc.state.ensure.assert_awaited_once_with(
        "oa:user-123", zalo_channel="oa", account_key=None
    )
    svc.state.apply_follow.assert_awaited_once_with(conv)
    svc.state.apply_unfollow.assert_not_called()


@pytest.mark.asyncio
async def test_oa_unfollow_opted_out_and_records_system_note(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.apply_unfollow = AsyncMock(return_value=conv)
    svc.state.record_system_note = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(
        MagicMock(),
        {"event_name": "unfollow", "follower": {"id": "user-123"}},
        enqueue=lambda _j: True,
        channel="oa",
    )

    assert result == {"status": "unfollow"}
    svc.state.apply_unfollow.assert_awaited_once_with(conv)
    svc.state.record_system_note.assert_awaited_once()
    assert "unfollow" in svc.state.record_system_note.call_args.kwargs["body"].lower()


@pytest.mark.asyncio
async def test_oa_button_click_records_system_note(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=uuid.uuid4())
    svc = MagicMock()
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.record_system_note = AsyncMock()
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
    body = svc.state.record_system_note.call_args.kwargs["body"]
    assert "Xem chi tiết" in body


@pytest.mark.asyncio
async def test_oa_media_event_returns_ignored_without_db_write(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    svc = MagicMock()
    svc.state.ensure = AsyncMock()
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
    svc.state.ensure.assert_not_called()


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
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.record_inbound = AsyncMock()
    svc.repo.get = AsyncMock(return_value=conv)
    svc.repo.inbound_is_answered = AsyncMock(return_value=False)
    svc.state.run_start_guard = MagicMock(return_value=True)
    svc.state.bot_paused = AsyncMock(return_value=False)
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    svc.state.acquire_lock = AsyncMock(return_value=lock_owner)
    svc.state.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )

    # Capture the best-effort OA profile enrichment enqueue (fire-and-forget on
    # the persistence_low queue). Mocked so the test never touches Redis.
    enrich_calls: list[dict] = []

    def _fake_enqueue_enrich(job):
        enrich_calls.append(job)

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
        enrich_oa_profile=_fake_enqueue_enrich,
    )

    assert result["status"] == "processing"
    assert len(enqueued) == 1
    assert enqueued[0]["user_text"] == "Xin chào"
    assert enqueued[0]["lock_owner"] == str(lock_owner)
    assert enqueued[0]["execution_source"] == "queued"
    # The OA profile enrichment job is enqueued fire-and-forget with the
    # conversation-scoped zalo_id and the external OA user id.
    assert len(enrich_calls) == 1
    assert enrich_calls[0] == {
        "zalo_id": "oa:user-123",
        "user_id": "user-123",
        # Multi-OA: the enrichment authenticates as the OA that received the
        # message; empty means the seeded original OA.
        "account_key": "",
    }


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


async def test_ingress_delegates_status_to_the_owned_turn_without_orphan_requests(monkeypatch):
    """Both jobs retain provider identity; only the tracked Bot bridge may pulse."""
    import uuid

    import app.services.webhook as webhook_module
    from app.services.webhook import ZaloWebhookService

    fired: list[str] = []
    jobs: list[dict] = []

    async def _record_typing(chat_id, bot_token=None):  # noqa: ARG001
        fired.append(chat_id)

    monkeypatch.setattr(webhook_module, "_fire_typing", _record_typing)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
        AsyncMock(return_value=None),
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    async def _run_handle_for(channel: str) -> None:
        conv = SimpleNamespace(
            id=uuid.uuid4(),
            zalo_chat_id="chat-user-1",
            zalo_channel=channel,
            version=1,
            mode="BOT",
        )
        service = MagicMock()
        service.state.ensure = AsyncMock(return_value=conv)
        service.state.record_inbound = AsyncMock()
        service.repo.get = AsyncMock(return_value=conv)
        service.repo.inbound_is_answered = AsyncMock(return_value=False)
        service.state.run_start_guard = MagicMock(return_value=True)
        service.state.bot_paused = AsyncMock(return_value=False)
        service.state.acquire_lock = AsyncMock(
            return_value=uuid.UUID("00000000-0000-0000-0000-000000000002")
        )
        monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)

        if channel == "bot":
            payload = {
                "message": {"message_id": "msg-1", "chat": {"id": "chat-user-1"}, "text": "Xin chào"}
            }
            return await ZaloWebhookService.handle(
                db, payload, enqueue=lambda job: jobs.append(job) or True
            )
        payload = {
            "event_name": "user_send_text",
            "sender": {"id": "chat-user-1"},
            "message": {"msg_id": "msg-oa-1", "text": "Xin chào"},
        }
        return await ZaloWebhookService.handle(
            db,
            payload,
            enqueue=lambda job: jobs.append(job) or True,
            channel="oa",
        )

    await _run_handle_for("bot")
    await _run_handle_for("oa")
    await asyncio.sleep(0)

    assert fired == []
    assert [job["zalo_channel"] for job in jobs] == ["bot", "oa"]
    assert [job["zalo_chat_id"] for job in jobs] == ["chat-user-1", "oa:chat-user-1"]


# ─── Phase 1 characterization: send-error classification taxonomy ────────────
#
# The neutral ChannelSendResult reuses the canonical error_class taxonomy from
# app.shared.application.outbound. These tests freeze that mapping so adapters
# adapter wrappers and Phase 5's Messenger adapter cannot drift it.


def test_phase1_ambiguous_transport_classes_map_to_send_unknown():
    """The conservative classifier: any failure that MAY have reached the
    provider after the request was written is non-retriable SEND_UNKNOWN.
    """
    from app.shared.application.outbound import (
        AMBIGUOUS_SEND_CLASSES,
        is_ambiguous_send,
    )

    for cls in AMBIGUOUS_SEND_CLASSES:
        assert is_ambiguous_send(cls, ok=False), f"{cls} should map to SEND_UNKNOWN"


def test_phase1_connect_error_is_retryable_failed_not_send_unknown():
    """A definite pre-send connection failure is retryable FAILED, not
    terminal SEND_UNKNOWN. Phase 3/5 adapters must preserve this distinction.
    """
    from app.shared.application.outbound import is_ambiguous_send

    assert not is_ambiguous_send("connect_error", ok=False)
    # None → caller falls back to default FAILED (retryable)


def test_phase1_send_classification_is_provider_neutral():
    """The taxonomy module's executable code imports no provider module and
    branches on no provider id — the proof that the SEND_UNKNOWN decision
    does not branch on Zalo vs Facebook. Docstrings may mention Zalo as
    historical context; the *code* must not.
    """
    import ast
    import inspect

    from app.shared.application import outbound

    src = inspect.getsource(outbound)
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
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.repo.get = AsyncMock(return_value=conv)
    svc.repo.inbound_is_answered = AsyncMock(return_value=False)
    svc.state.record_inbound = AsyncMock()
    svc.state.run_start_guard = lambda c: True
    svc.state.bot_paused = AsyncMock(return_value=False)
    svc.state.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    svc.state.release_lock = AsyncMock()
    # ConversationService + CandidateExtractionService + dedup are imported
    # inside handle() — patch the service module where they're looked up.
    import app.services.webhook as wh_mod
    from app.services import candidate_extraction as ce_mod

    monkeypatch.setattr(wh_mod, "ConversationService", lambda _db: svc)
    monkeypatch.setattr(ce_mod, "CandidateExtractionService", SimpleNamespace(
        persist_explicit_details=AsyncMock()
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


@pytest.mark.asyncio
async def test_enqueue_chat_turn_async_runs_the_sync_core_off_the_event_loop(monkeypatch):
    """The awaited wrapper must hand the synchronous redis/RQ core to a worker
    thread, so the ASGI loop never blocks on it, and pass its result through."""
    import threading

    from app.api import webhooks
    from app.composition import conversation_messaging as messaging

    loop_thread = threading.get_ident()
    seen: dict[str, object] = {}

    def fake_sync_enqueue(job):
        seen["thread"] = threading.get_ident()
        seen["job"] = job
        return False  # the backpressure signal callers map to 503

    monkeypatch.setattr(messaging, "enqueue_chat_turn", fake_sync_enqueue)

    result = await webhooks.enqueue_chat_turn_async({"conversation_id": "c1"})

    assert result is False
    assert seen["job"] == {"conversation_id": "c1"}
    assert seen["thread"] != loop_thread, "the sync enqueue ran on the event-loop thread"


@pytest.mark.asyncio
async def test_enqueue_chat_turn_async_keeps_the_event_loop_responsive(monkeypatch):
    """A blocking sync enqueue must not freeze the loop: while it waits, other
    loop work still completes well before the sync body is released."""
    import threading

    from app.api import webhooks
    from app.composition import conversation_messaging as messaging

    release = threading.Event()

    def blocking_enqueue(_job):
        release.wait(timeout=5)
        return True

    monkeypatch.setattr(messaging, "enqueue_chat_turn", blocking_enqueue)

    loop = asyncio.get_running_loop()
    start = loop.time()
    task = asyncio.create_task(webhooks.enqueue_chat_turn_async({"conversation_id": "c1"}))
    try:
        # Yields to the loop once. If the enqueue ran on-loop, this could not
        # return until the 5s thread wait elapsed.
        await asyncio.sleep(0.05)
        elapsed = loop.time() - start
    finally:
        release.set()

    assert elapsed < 1.0, "the event loop was blocked by the synchronous enqueue"
    assert await task is True


@pytest.mark.asyncio
async def test_async_enqueue_wrapper_preserves_backpressure_start_failed(monkeypatch):
    """Awaiting the wrapper keeps the existing backpressure mapping: a False
    enqueue still yields start_failed (503 to Zalo) and releases the lock."""
    from app.api import webhooks
    from app.composition import conversation_messaging as messaging
    from app.services.webhook import ZaloWebhookService

    monkeypatch.setattr(messaging, "enqueue_chat_turn", lambda _job: False)

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000ab")
    service = MagicMock()
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=lock_owner)
    service.state.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    result = await ZaloWebhookService.handle(
        db,
        {"message": {"message_id": "msg-1", "chat": {"id": "bot-user-1"}, "text": "Xin chào"}},
        enqueue=webhooks.enqueue_chat_turn_async,
    )

    assert result == {"status": "start_failed", "conversation_id": str(conv.id)}
    service.state.release_lock.assert_awaited_once_with(conv, lock_owner=lock_owner)


@pytest.mark.asyncio
async def test_zalo_route_awaits_async_enqueue_and_maps_backpressure_to_503(monkeypatch):
    """End-to-end through the route and the real handler: the wired wrapper is
    awaited, and a backpressured (False) enqueue still yields the 503 Zalo
    retries on, releasing the per-chat lock."""
    from app.api import webhooks
    from app.composition import conversation_messaging as messaging

    monkeypatch.setattr(messaging, "enqueue_chat_turn", lambda _job: False)

    cfg = SimpleNamespace(bot_webhook_secret="", bot_token="bot-token")
    monkeypatch.setattr(
        webhooks,
        "IntegrationSettingsService",
        lambda _db: SimpleNamespace(resolve_zalo=AsyncMock(return_value=cfg)),
    )
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=None))

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=1,
        mode="BOT",
    )
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000ac")
    service = MagicMock()
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(return_value=lock_owner)
    service.state.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
        AsyncMock(return_value=None),
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    response = await webhooks.zalo_webhook(
        FakeRequest(
            json.dumps(
                {
                    "message": {
                        "message_id": "msg-1",
                        "chat": {"id": "bot-user-1"},
                        "text": "Xin chào",
                    }
                }
            ).encode()
        ),
        db=db,
    )

    assert response.status_code == 503
    service.state.release_lock.assert_awaited_once_with(conv, lock_owner=lock_owner)

# ─── the ack path's conversation reloads (PERF-15) ───────────────────────────
#
# ``Conversation.contact`` / ``.channel_identity`` are ``lazy="selectin"``, so a
# full ``db.refresh(conv)`` re-fetches two extra rows on top of the conversation
# itself. The ingress path used to pay that three times per inbound message, on
# the <1s ack that also stamps webhook_ack_ms. Exactly one column-scoped reload
# remains — the one immediately before the guard chain and ``acquire_lock``,
# which is what makes the takeover race guard correct.


def _ack_path_service(conv):
    service = MagicMock()
    service.state.ensure = AsyncMock(return_value=conv)
    service.state.record_inbound = AsyncMock()
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    service.state.run_start_guard = MagicMock(return_value=True)
    service.state.bot_paused = AsyncMock(return_value=False)
    service.state.acquire_lock = AsyncMock(
        return_value=uuid.UUID("00000000-0000-0000-8000-000000000002")
    )
    return service


def _ack_conv():
    return SimpleNamespace(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        zalo_chat_id="bot-user-1",
        zalo_channel="bot",
        version=3,
        mode="BOT",
    )


@pytest.mark.asyncio
async def test_ack_path_refreshes_the_conversation_exactly_once(monkeypatch):
    """One column-scoped reload per inbound message, not three full ones."""
    from app.services.webhook import ZaloWebhookService

    conv = _ack_conv()
    service = _ack_path_service(conv)
    order: list[str] = []

    async def _acquire_lock(_conv_id):
        order.append("acquire_lock")
        return uuid.UUID("00000000-0000-4000-8000-000000000002")

    service.state.acquire_lock = AsyncMock(side_effect=_acquire_lock)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
        AsyncMock(return_value=None),
    )
    db = MagicMock()

    async def _refresh(_conv, attribute_names=None):
        order.append("refresh")

    db.refresh = AsyncMock(side_effect=_refresh)
    jobs: list[dict] = []

    result = await ZaloWebhookService.handle(
        db,
        {"message": {"message_id": "msg-1", "chat": {"id": "bot-user-1"}, "text": "Xin chào"}},
        enqueue=lambda job: jobs.append(job) or True,
        runtime_authority=_runtime_authority(),
    )

    assert result == {"status": "processing", "conversation_id": str(conv.id)}
    # Exactly one reload on the ingress path.
    assert order.count("refresh") == 1
    # ...and it is the one that guards the lock acquisition, not a duplicate.
    assert order == ["refresh", "acquire_lock"]
    assert db.refresh.await_args.args[1] == [
        "mode",
        "status",
        "version",
        "taken_over_at",
        "assigned_recruiter_id",
        "updated_at",
        "bot_locked_until",
        "bot_lock_owner",
    ]


@pytest.mark.asyncio
async def test_ack_path_does_not_re_read_the_conversation_through_the_service(
    monkeypatch,
):
    """The identity-map read through the repository is gone from the ack path."""
    from app.services.webhook import ZaloWebhookService

    conv = _ack_conv()
    service = _ack_path_service(conv)
    service.repo.get = AsyncMock(return_value=conv)
    service.repo.inbound_is_answered = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: service)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "app.services.candidate_extraction.CandidateExtractionService.persist_explicit_details",
        AsyncMock(return_value=None),
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    await ZaloWebhookService.handle(
        db,
        {"message": {"message_id": "msg-1", "chat": {"id": "bot-user-1"}, "text": "Xin chào"}},
        enqueue=lambda _job: True,
        runtime_authority=_runtime_authority(),
    )

    service.repo.get.assert_not_called()


# ─── the dormant runtime-authority gate (OPS-26) ─────────────────────────────
#
# ``resolve_active()`` returns None on every production message until the
# installation tables are populated, so the line that announces it fired on 100%
# of traffic. At INFO it drowned every real signal, and an alert on it would
# page on all traffic while a genuine regression of the authority rollout stayed
# invisible behind the noise.


@pytest.mark.asyncio
async def test_inactive_runtime_authority_is_debug_after_the_first_summary(
    monkeypatch, caplog
):
    """The per-message line is DEBUG; only the first is an INFO summary."""
    import logging

    from app.api import webhooks

    webhooks._RUNTIME_INACTIVE.reset()
    monkeypatch.setattr(
        webhooks,
        "InstallationService",
        lambda _db: SimpleNamespace(resolve_active=AsyncMock(return_value=None)),
    )

    with caplog.at_level(logging.DEBUG, logger="app.api.webhooks"):
        for _ in range(3):
            assert await webhooks._runtime_authority_or_inactive(
                AsyncMock(), channel="bot"
            ) is None

    records = [r for r in caplog.records if "runtime inactive" in r.getMessage()]
    # One INFO summary for the process; the rest never reach an INFO handler.
    assert [r.levelno for r in records] == [logging.INFO, logging.DEBUG, logging.DEBUG]
    assert records[-1].getMessage().endswith("seen=3")
    # The counter is the once-per-process summary an operator can read instead.
    assert webhooks._RUNTIME_INACTIVE.seen == 3
    webhooks._RUNTIME_INACTIVE.reset()


@pytest.mark.asyncio
async def test_active_runtime_authority_is_untouched_by_the_tally(monkeypatch):
    """A deployment WITH an active installation never touches the summary."""
    from app.api import webhooks

    webhooks._RUNTIME_INACTIVE.reset()
    authority = _runtime_authority()
    monkeypatch.setattr(
        webhooks,
        "InstallationService",
        lambda _db: SimpleNamespace(
            resolve_active=AsyncMock(
                return_value=SimpleNamespace(
                    fingerprint=SimpleNamespace(stamp=lambda: authority)
                )
            )
        ),
    )

    stamp = await webhooks._runtime_authority_or_inactive(AsyncMock(), channel="bot")

    assert stamp is authority
    assert webhooks._RUNTIME_INACTIVE.seen == 0


@pytest.mark.asyncio
async def test_messenger_ad_prefill_message_is_flagged_and_skipped(monkeypatch):
    """A Click-to-Messenger ad's pre-filled message never opens Meta's 24h
    window (it is page-initiated content), so an automated reply is always
    refused (code 10, subcode 2018278) — production 2026-10-07. The webhook
    must flag the thread (staying in BOT mode) and enqueue no turn."""
    import json

    from app.api import webhooks

    conversation_id = uuid.uuid4()
    persisted = SimpleNamespace(
        conversation_id=str(conversation_id),
        body="Công ty có xe đưa đón không?",
        provider_message_id="mid-ad-1",
        created_at=None,
        id=17,
    )
    outcome = SimpleNamespace(
        status="persisted", message=persisted, conversation_id=str(conversation_id)
    )

    class FakeIngress:
        def __init__(self, db) -> None:
            pass

        async def ingest(self, _message):
            return outcome

    monkeypatch.setattr(webhooks, "enforce_webhook_rate_limit", AsyncMock())
    monkeypatch.setattr(webhooks, "IntegrationSettingsService",
                        lambda _db: SimpleNamespace(
                            resolve_facebook_oauth=AsyncMock(return_value=SimpleNamespace(app_secret="s"))))
    monkeypatch.setattr(
        "app.channels.providers.facebook_signature.verify_messenger_signature",
        lambda **_kwargs: SimpleNamespace(verified=True, reason=None),
    )
    monkeypatch.setattr(
        webhooks,
        "_resolve_active_facebook_page",
        AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace(account_key="page-1"))),
    )
    monkeypatch.setattr("app.channels.ingress.ChannelIngressService", FakeIngress)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=None))
    monkeypatch.setattr(webhooks, "enqueue_messenger_profile_enrichment", MagicMock())
    flagged = AsyncMock(return_value=False)
    monkeypatch.setattr(webhooks, "messenger_ad_entry_flagged", flagged)
    turn = AsyncMock()
    monkeypatch.setattr(webhooks, "enqueue_facebook_turn", turn)
    monkeypatch.setattr(webhooks, "record_webhook_ack_ms", AsyncMock())

    payload = json.dumps({
        "entry": [{
            "messaging": [{
                "sender": {"id": "psid-1"},
                "recipient": {"id": "page-1"},
                "message": {
                    "mid": "mid-ad-1",
                    "text": "Công ty có xe đưa đón không?",
                    "referral": {"source": "ADS", "ad_id": "ad-1"},
                },
            }]
        }]
    })

    response = await webhooks.facebook_webhook(
        FakeRequest(payload), db=MagicMock()
    )

    assert response.status_code == 200
    flagged.assert_awaited_once()
    # The marker rides genuine first messages too, so the turn runs and the
    # attempt itself is the test.
    turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_messenger_genuine_message_clears_the_flag_and_rides_the_normal_path(
    monkeypatch,
):
    """A message without the ad-referral marker is a real candidate message:
    the escalation is skipped and the turn is enqueued as usual."""
    import json

    from app.api import webhooks

    conversation_id = uuid.uuid4()
    persisted = SimpleNamespace(
        conversation_id=str(conversation_id),
        body="LG Hải Phòng",
        provider_message_id="mid-real-1",
        created_at=None,
        id=18,
    )
    outcome = SimpleNamespace(
        status="persisted", message=persisted, conversation_id=str(conversation_id)
    )

    class FakeIngress:
        def __init__(self, db) -> None:
            pass

        async def ingest(self, _message):
            return outcome

    monkeypatch.setattr(webhooks, "enforce_webhook_rate_limit", AsyncMock())
    monkeypatch.setattr(webhooks, "IntegrationSettingsService",
                        lambda _db: SimpleNamespace(
                            resolve_facebook_oauth=AsyncMock(return_value=SimpleNamespace(app_secret="s"))))
    monkeypatch.setattr(
        "app.channels.providers.facebook_signature.verify_messenger_signature",
        lambda **_kwargs: SimpleNamespace(verified=True, reason=None),
    )
    monkeypatch.setattr(
        webhooks,
        "_resolve_active_facebook_page",
        AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace(account_key="page-1"))),
    )
    monkeypatch.setattr("app.channels.ingress.ChannelIngressService", FakeIngress)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=None))
    monkeypatch.setattr(webhooks, "enqueue_messenger_profile_enrichment", MagicMock())
    flagged = AsyncMock(return_value=False)
    monkeypatch.setattr(webhooks, "messenger_ad_entry_flagged", flagged)
    cleared = AsyncMock(return_value=False)
    monkeypatch.setattr(webhooks, "clear_messenger_ad_entry_flag", cleared)
    turn = AsyncMock()
    monkeypatch.setattr(webhooks, "enqueue_facebook_turn", turn)
    monkeypatch.setattr(webhooks, "record_webhook_ack_ms", AsyncMock())

    payload = json.dumps({
        "entry": [{
            "messaging": [{
                "sender": {"id": "psid-1"},
                "recipient": {"id": "page-1"},
                "message": {"mid": "mid-real-1", "text": "LG Hải Phòng"},
            }]
        }]
    })

    response = await webhooks.facebook_webhook(
        FakeRequest(payload), db=MagicMock()
    )

    assert response.status_code == 200
    flagged.assert_not_awaited()
    cleared.assert_awaited_once()
    turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_messenger_referral_message_on_a_flagged_thread_is_skipped(monkeypatch):
    """Once a send has been refused with the closed-window error the thread is
    flagged; the next ad-referral message (a re-click prefill) is skipped
    quietly instead of burning another doomed turn. A genuine message has no
    marker, so it never reaches this branch — it clears the flag instead."""

    from app.api import webhooks

    conversation_id = uuid.uuid4()
    persisted = SimpleNamespace(
        conversation_id=str(conversation_id),
        body="Công ty có xe đưa đón không?",
        provider_message_id="mid-ad-2",
        created_at=None,
        id=19,
    )
    outcome = SimpleNamespace(
        status="persisted", message=persisted, conversation_id=str(conversation_id)
    )

    class FakeIngress:
        def __init__(self, db) -> None:
            pass

        async def ingest(self, _message):
            return outcome

    monkeypatch.setattr(webhooks, "enforce_webhook_rate_limit", AsyncMock())
    monkeypatch.setattr(webhooks, "IntegrationSettingsService",
                        lambda _db: SimpleNamespace(
                            resolve_facebook_oauth=AsyncMock(return_value=SimpleNamespace(app_secret="s"))))
    monkeypatch.setattr(
        "app.channels.providers.facebook_signature.verify_messenger_signature",
        lambda **_kwargs: SimpleNamespace(verified=True, reason=None),
    )
    monkeypatch.setattr(
        webhooks,
        "_resolve_active_facebook_page",
        AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace(account_key="page-1"))),
    )
    monkeypatch.setattr("app.channels.ingress.ChannelIngressService", FakeIngress)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=None))
    monkeypatch.setattr(webhooks, "enqueue_messenger_profile_enrichment", MagicMock())
    flagged = AsyncMock(return_value=True)
    monkeypatch.setattr(webhooks, "messenger_ad_entry_flagged", flagged)
    cleared = AsyncMock()
    monkeypatch.setattr(webhooks, "clear_messenger_ad_entry_flag", cleared)
    turn = AsyncMock()
    monkeypatch.setattr(webhooks, "enqueue_facebook_turn", turn)
    monkeypatch.setattr(webhooks, "record_webhook_ack_ms", AsyncMock())

    payload = json.dumps({
        "entry": [{
            "messaging": [{
                "sender": {"id": "psid-1"},
                "recipient": {"id": "page-1"},
                "message": {
                    "mid": "mid-ad-2",
                    "text": "Công ty có xe đưa đón không?",
                    "referral": {"source": "ADS", "ad_id": "ad-1"},
                },
            }]
        }]
    }).encode()

    response = await webhooks.facebook_webhook(
        FakeRequest(payload), db=MagicMock()
    )

    assert response.status_code == 200
    flagged.assert_awaited_once()
    cleared.assert_not_awaited()
    turn.assert_not_awaited()


# ── Payroll-pushed TingTing OA token (POST /webhooks/zalo-oa-token) ─────────


def _patch_token_push(monkeypatch, *, stored_key: str | None):
    """Wire the push route's three collaborators with recorder doubles."""
    from app.api import webhooks
    from app.services import tingting_api as tingting_mod

    writes: list[tuple[str, str]] = []

    async def fake_store(account_key, access_token):  # noqa: ANN001
        writes.append((account_key, access_token))
        return [f"zalo_oa_access_token:{account_key}"]

    fake_settings = SimpleNamespace(
        store_pushed_oa_token=AsyncMock(side_effect=fake_store)
    )
    monkeypatch.setattr(
        webhooks, "IntegrationSettingsService", lambda _db: fake_settings
    )
    runtime = (
        SimpleNamespace(api_key=stored_key) if stored_key is not None else None
    )
    monkeypatch.setattr(
        tingting_mod.TingtingApiService,
        "runtime",
        AsyncMock(return_value=runtime),
    )
    audits: list[dict] = []
    monkeypatch.setattr(
        "app.services.audit_service.record_audit",
        AsyncMock(side_effect=lambda _db, **kw: audits.append(kw) or None),
    )
    return writes, audits


@pytest.mark.asyncio
async def test_token_push_stores_the_tingting_access_token(monkeypatch, caplog):
    from app.api import webhooks
    writes, _audits = _patch_token_push(monkeypatch, stored_key="k-1")

    response = await webhooks.zalo_oa_token_webhook(
        FakeRequest(
            json.dumps({"access_token": "at-secret-1"}).encode(),
            headers={"x-api-key": "k-1"},
        ),
        db=AsyncMock(),
    )

    assert response.status_code == 200
    assert response.body == b'{"status":"stored"}'
    assert writes == [("tingting", "at-secret-1")]
    # The token must never reach the logs, in any form.
    assert "at-secret-1" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"x-api-key": "wrong-key"}])
async def test_token_push_rejects_a_bad_or_missing_api_key(monkeypatch, headers):
    from app.api import webhooks
    _patch_token_push(monkeypatch, stored_key="k-1")

    response = await webhooks.zalo_oa_token_webhook(
        FakeRequest(
            json.dumps({"access_token": "at-secret-1"}).encode(), headers=headers
        ),
        db=AsyncMock(),
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_push_without_a_configured_api_key_is_401(monkeypatch):
    from app.api import webhooks
    _patch_token_push(monkeypatch, stored_key=None)

    response = await webhooks.zalo_oa_token_webhook(
        FakeRequest(
            json.dumps({"access_token": "at-secret-1"}).encode(),
            headers={"x-api-key": "k-1"},
        ),
        db=AsyncMock(),
    )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"detail": "no token here"}).encode(),
        json.dumps({"access_token": "   "}).encode(),
        b'{"access_token": ',
    ],
)
async def test_token_push_rejects_a_body_without_a_token(monkeypatch, body):
    from app.api import webhooks
    writes, _audits = _patch_token_push(monkeypatch, stored_key="k-1")

    response = await webhooks.zalo_oa_token_webhook(
        FakeRequest(body, headers={"x-api-key": "k-1"}),
        db=AsyncMock(),
    )

    assert response.status_code == 400
    assert writes == []
