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
