from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from app.conversation_messaging.application.ingress import (
    InboundIngressResult,
    PersistedInboundMessage,
)
from app.conversation_messaging.infrastructure import webhook_delivery


def _persisted_outcome(conversation_id: uuid.UUID) -> InboundIngressResult:
    return InboundIngressResult(
        status="persisted",
        message=PersistedInboundMessage(
            conversation_id=str(conversation_id),
            message_id=17,
            body="Công ty có xe đưa đón không?",
            provider_message_id="facebook-mid-17",
            created_at=datetime(2026, 10, 7, 5, 49, 38, tzinfo=UTC),
        ),
    )


async def test_facebook_turn_uses_exact_persisted_message(monkeypatch) -> None:
    conversation_id = uuid.uuid4()
    conversation = SimpleNamespace(id=conversation_id, version=11)
    lock_owner = uuid.uuid4()

    class Service:
        def __init__(self, db) -> None:
            pass

        get = AsyncMock(return_value=conversation)
        acquire_lock = AsyncMock(return_value=lock_owner)
        release_lock = AsyncMock()

        def run_start_guard(self, candidate) -> bool:
            return True

    monkeypatch.setattr(webhook_delivery, "ConversationService", Service)
    db = SimpleNamespace(scalar=AsyncMock(return_value=conversation))
    persisted_at = datetime(2026, 7, 23, 3, 4, 5, tzinfo=UTC)
    outcome = InboundIngressResult(
        status="persisted",
        message=PersistedInboundMessage(
            conversation_id=str(conversation_id),
            message_id=17,
            body="the exact inbound body",
            provider_message_id="facebook-mid-17",
            created_at=persisted_at,
        ),
    )
    enqueued: list[dict] = []

    await webhook_delivery.enqueue_facebook_turn(
        db,
        outcome,
        runtime_authority=None,
        enqueue=lambda job: enqueued.append(job) or True,
    )

    assert enqueued[0]["user_text"] == "the exact inbound body"
    assert enqueued[0]["reply_to_message_id"] == "facebook-mid-17"
    assert enqueued[0]["received_at"] == persisted_at.isoformat()
    assert not hasattr(db, "scalars")


async def test_ad_entry_prefill_escalates_a_first_and_only_message(monkeypatch) -> None:
    """A thread whose whole history is the ad prefill parks for human review."""
    conversation_id = uuid.uuid4()
    conversation = SimpleNamespace(id=conversation_id, version=3)
    escalated: list[tuple[object, int]] = []

    class Service:
        def __init__(self, db) -> None:
            pass

        async def mark_ad_entry_prefill(self, conv, *, expected_version):
            escalated.append((conv, expected_version))
            return True

    monkeypatch.setattr(webhook_delivery, "ConversationService", Service)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[conversation, 1]))

    assert (
        await webhook_delivery.escalate_messenger_ad_entry(db, _persisted_outcome(conversation_id))
        is True
    )
    assert escalated == [(conversation, 3)]


async def test_ad_entry_prefill_leaves_an_existing_conversation_on_the_bot_path(
    monkeypatch,
) -> None:
    """A re-click inside a thread the candidate has chatted in rides the normal path."""

    conversation_id = uuid.uuid4()
    conversation = SimpleNamespace(id=conversation_id, version=9)

    class Service:
        def __init__(self, db) -> None:
            raise AssertionError("an existing thread must never be escalated here")

    monkeypatch.setattr(webhook_delivery, "ConversationService", Service)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[conversation, 4]))

    assert (
        await webhook_delivery.escalate_messenger_ad_entry(db, _persisted_outcome(conversation_id))
        is False
    )


async def test_ad_entry_prefill_ignores_an_outcome_without_a_message() -> None:
    db = SimpleNamespace(scalar=AsyncMock())

    assert (
        await webhook_delivery.escalate_messenger_ad_entry(
            db, InboundIngressResult(status="duplicate")
        )
        is False
    )
    db.scalar.assert_not_awaited()
