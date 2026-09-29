"""The post-send extraction escalation keeps its lock semantics after the reply.

Operator rule 2026-09-29 removed the TingTing support OA's in-lane consultant
handoff (nobody works that OA; its would-be escalations return the hotline
reply instead), so no answer lane escalates inside a turn anymore. What
remains is the post-send extraction escalation (candidate_extraction.py),
which runs AFTER the reply is out and must keep releasing the per-chat lock
and bumping the version to invalidate stale writers — the same state-layer
contract the deleted support-OA handoff used to exercise in-lane.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models.conversation import (
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.services.conversation.state import ConversationState, utcnow
from tests.integration._conv_factory import make_zalo_conversation


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        return None

    async def conversation_updated(self, _conversation) -> None:
        return None


async def _seed(db) -> tuple[Conversation, Message, uuid.UUID]:
    """A zalo thread pre-locked exactly as the webhook leaves it."""
    owner = uuid.uuid4()
    conv = await make_zalo_conversation(
        db,
        zalo_chat_id="extraction-escalation-claim",
        zalo_channel="bot",
        mode=ConversationMode.BOT,
        bot_lock_owner=owner,
        bot_locked_until=utcnow() + timedelta(seconds=180),
        bot_lock_heartbeat_at=utcnow(),
    )
    pending = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body="Đang soạn trả lời...",
        delivery_status=DeliveryStatus.PENDING,
    )
    db.add(pending)
    await db.flush()
    await db.commit()
    return conv, pending, owner


@pytest.mark.asyncio
async def test_post_send_extraction_escalation_still_releases_the_lock(
    integration_session,
) -> None:
    """The extraction job runs after the reply: it keeps bumping and unlocking."""
    conv, _pending, owner = await _seed(integration_session)
    svc = ConversationState(integration_session, repo=None, events=_NoopEvents())
    version_before = conv.version

    assert await svc.escalate_extracted_intent(
        conv,
        reason="bot_testing",
        confidence=0.99,
        expected_version=version_before,
    )

    await integration_session.refresh(conv)
    assert conv.version == version_before + 1
    assert conv.bot_lock_owner is None
    assert conv.bot_locked_until is None
    assert conv.bot_lock_heartbeat_at is None
    assert conv.mode == ConversationMode.HUMAN
