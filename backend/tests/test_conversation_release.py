"""Conversation release dispatch tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_release_dispatches_unanswered_turn_through_rq(monkeypatch) -> None:
    from app.api import conversations

    conversation = SimpleNamespace()
    service = SimpleNamespace(release_and_enqueue_unanswered=AsyncMock(return_value=conversation))
    expected = object()
    monkeypatch.setattr(conversations, "ConversationService", lambda _db: service)
    monkeypatch.setattr(conversations, "_load", AsyncMock(return_value=conversation))
    monkeypatch.setattr(
        conversations.ConversationOut,
        "model_validate",
        MagicMock(return_value=expected),
    )

    result = await conversations.release(
        uuid.uuid4(),
        user=SimpleNamespace(),
        db=AsyncMock(),
    )

    assert result is expected
    kwargs = service.release_and_enqueue_unanswered.await_args.kwargs
    assert kwargs["enqueue"] is conversations.enqueue_chat_run


@pytest.mark.asyncio
async def test_release_enqueue_failure_releases_owner_token_lock() -> None:
    from app.services.conversation.scheduler import enqueue_latest_unanswered_worker_message

    conversation = SimpleNamespace(id=uuid.uuid4(), version=3)
    pending = SimpleNamespace(
        body="Tin nhắn chưa trả lời",
        zalo_message_id="zalo-msg-1",
        created_at=datetime.now(timezone.utc),
    )
    lock_owner = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    service = SimpleNamespace(
        latest_unanswered_worker_message=AsyncMock(return_value=pending),
        acquire_lock=AsyncMock(return_value=lock_owner),
        release_lock=AsyncMock(),
    )
    jobs: list[dict] = []

    def fail_enqueue(job: dict) -> bool:
        jobs.append(job)
        return False

    result = await enqueue_latest_unanswered_worker_message(
        service,
        conversation,
        enqueue=fail_enqueue,
    )

    assert result is False
    assert jobs[0]["execution_source"] == "queued"
    service.release_lock.assert_awaited_once_with(
        conversation,
        lock_owner=lock_owner,
    )
