"""Conversation release dispatch tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def first(self) -> object | None:
        return self.value


@pytest.mark.asyncio
async def test_release_treats_delivered_or_read_recruiter_replies_as_answers() -> None:
    """A Zalo receipt must not let release replay an already answered inbound."""
    from app.models.conversation import DeliveryStatus
    from app.services.conversation.repository import ConversationRepository

    conversation = SimpleNamespace(id=uuid.uuid4())
    worker_message = SimpleNamespace(id=101)
    db = MagicMock()
    db.scalars = AsyncMock(
        side_effect=[_ScalarResult(worker_message), _ScalarResult(None)]
    )

    await ConversationRepository(db).latest_unanswered_worker_message(conversation)

    answered_query = db.scalars.await_args_list[1].args[0]
    params = answered_query.compile().params
    assert set(params["delivery_status_1"]) == {
        DeliveryStatus.SENT,
        DeliveryStatus.DELIVERED,
        DeliveryStatus.READ,
    }


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


@pytest.mark.asyncio
async def test_unassigned_human_review_must_be_claimed_before_release(monkeypatch) -> None:
    from app.models.user import Role
    from app.services.conversation.state import ConversationConflict, ConversationState

    conv = SimpleNamespace(id=uuid.uuid4(), assigned_recruiter_id=None)
    actor = SimpleNamespace(id=uuid.uuid4(), role=Role.recruiter)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(0))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    with pytest.raises(ConversationConflict, match="claimed before release"):
        await ConversationState(db, MagicMock(), MagicMock()).release(conv, actor)

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_release_clears_human_review_flag(monkeypatch) -> None:
    from app.models.conversation import ConversationMode
    from app.models.user import Role
    from app.services.conversation.state import ConversationState

    actor = SimpleNamespace(id=uuid.uuid4(), role=Role.recruiter)
    conv = SimpleNamespace(id=uuid.uuid4(), assigned_recruiter_id=actor.id)
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=_Result(1))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", audit)
    events = MagicMock(conversation_updated=AsyncMock())

    await ConversationState(db, MagicMock(), events).release(conv, actor)

    params = db.execute.await_args.args[0].compile().params
    assert params["mode"] == ConversationMode.BOT
    assert params["needs_human"] is False
    audit.assert_awaited_once()
    db.commit.assert_awaited_once()
    events.conversation_updated.assert_awaited_once_with(conv)


@pytest.mark.asyncio
async def test_release_does_not_commit_when_audit_write_fails(monkeypatch) -> None:
    from app.models.user import Role
    from app.services.conversation.state import ConversationState

    actor = SimpleNamespace(id=uuid.uuid4(), role=Role.recruiter)
    conv = SimpleNamespace(id=uuid.uuid4(), assigned_recruiter_id=actor.id)
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=_Result(1))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    monkeypatch.setattr(
        "app.services.conversation.state.record_audit",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await ConversationState(db, MagicMock(), MagicMock()).release(conv, actor)

    db.commit.assert_not_awaited()
