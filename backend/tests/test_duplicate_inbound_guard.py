"""The ingress and turn guards that stop one inbound being answered twice.

Production 2026-10-05: Zalo redelivered a candidate's "Có lương chưa" 33 s after
the first delivery. The ingress is idempotent on the provider id, so the
redelivery persisted nothing — and then enqueued a SECOND turn, which sent the
same hotline reply again (14:27:06 and 14:27:41, both quoting the same inbound).
The per-chat mutex serializes turns, it does not dedupe them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.conversation.repository import ConversationRepository

INBOUND_ID = "cf60c57b3625497c1033"


def _session(scalars: list[object]) -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=scalars)
    return db


@pytest.mark.asyncio
async def test_inbound_is_answered_only_when_a_terminal_reply_exists():
    conv = SimpleNamespace(id=uuid.uuid4())
    inbox_at = datetime(2026, 10, 5, 14, 27, 2, tzinfo=timezone.utc)

    # A delivered reply after the inbound -> answered.
    answered = ConversationRepository(_session([inbox_at, 9891]))
    assert await answered.inbound_is_answered(conv, provider_message_id=INBOUND_ID) is True

    # Only a PENDING placeholder (an in-flight turn) -> not answered, so the
    # turn that recovers it still runs.
    pending = ConversationRepository(_session([inbox_at, None]))
    assert await pending.inbound_is_answered(conv, provider_message_id=INBOUND_ID) is False


@pytest.mark.asyncio
async def test_inbound_is_answered_is_false_for_an_unknown_inbound():
    conv = SimpleNamespace(id=uuid.uuid4())

    repo = ConversationRepository(_session([None]))

    assert await repo.inbound_is_answered(conv, provider_message_id=INBOUND_ID) is False


@pytest.mark.asyncio
async def test_worker_guard_reads_the_repo_and_fails_open():
    from app.workers.chatbot_worker import _inbound_already_answered

    state = SimpleNamespace(conversation_id=str(uuid.uuid4()), reply_to_message_id=INBOUND_ID)

    answered = SimpleNamespace(
        repo=SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
            inbound_is_answered=AsyncMock(return_value=True),
        )
    )
    assert await _inbound_already_answered(answered, state) is True

    fresh = SimpleNamespace(
        repo=SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
            inbound_is_answered=AsyncMock(return_value=False),
        )
    )
    assert await _inbound_already_answered(fresh, state) is False

    # A read failure must let the turn run: answering twice is bad, never
    # answering is worse.
    broken = SimpleNamespace(repo=SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("db"))))
    assert await _inbound_already_answered(broken, state) is False


@pytest.mark.asyncio
async def test_webhook_skips_a_redelivery_whose_inbound_is_already_answered(monkeypatch):
    from app.services.webhook import ZaloWebhookService

    enqueued: list[dict] = []

    conv = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="chat-1",
        zalo_channel="bot",
        version=9,
        mode="BOT",
    )
    svc = AsyncMock()
    svc.state.ensure = AsyncMock(return_value=conv)
    svc.state.record_inbound = AsyncMock()
    svc.repo.get = AsyncMock(return_value=conv)
    svc.repo.inbound_is_answered = AsyncMock(return_value=True)
    svc.state.run_start_guard = MagicMock(return_value=True)
    svc.state.acquire_lock = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda _db: svc)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )

    result = await ZaloWebhookService.handle(
        AsyncMock(),
        {"message": {"text": "Có lương chưa", "chat": {"id": "chat-1"}, "message_id": 1}},
        enqueue=lambda job: enqueued.append(job) or True,
        channel="bot",
    )

    assert result["status"] == "already_answered"
    assert enqueued == []
    svc.state.acquire_lock.assert_not_awaited()
