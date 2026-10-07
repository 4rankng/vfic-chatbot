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


async def test_messenger_ad_entry_flagged_reads_the_thread_flag(monkeypatch) -> None:
    """The flag is what skips an ad thread's next referral message — stamped
    by the outcome recorder when Meta refuses a send with the closed-window
    error, cleared by the candidate's first genuine message."""
    conversation_id = uuid.uuid4()
    flagged_conv = SimpleNamespace(
        id=conversation_id,
        attribution={"ad_prefill_pending": "true", "ad_id": "ad-1"},
    )
    clean_conv = SimpleNamespace(id=uuid.uuid4(), attribution={})

    async def scalar(_stmt):
        return flagged_conv

    assert (
        await webhook_delivery.messenger_ad_entry_flagged(
            SimpleNamespace(scalar=AsyncMock(side_effect=scalar)), str(conversation_id)
        )
        is True
    )

    async def scalar_clean(_stmt):
        return clean_conv

    assert (
        await webhook_delivery.messenger_ad_entry_flagged(
            SimpleNamespace(scalar=AsyncMock(side_effect=scalar_clean)), str(clean_conv.id)
        )
        is False
    )


async def test_a_genuine_message_clears_the_ad_entry_prefill_flag(monkeypatch) -> None:
    """The candidate typing is what reopens Meta's window: the flag clears so
    the thread rides the normal bot path again."""
    conversation_id = uuid.uuid4()
    cleared: list[uuid.UUID] = []

    class Service:
        def __init__(self, db) -> None:
            pass

        async def clear_ad_entry_prefill_flag(self, conversation_id):
            cleared.append(conversation_id)
            return True

    monkeypatch.setattr(webhook_delivery, "ConversationService", Service)
    db = SimpleNamespace()

    assert (
        await webhook_delivery.clear_messenger_ad_entry_flag(db, str(conversation_id)) is True
    )
    assert cleared == [conversation_id]
