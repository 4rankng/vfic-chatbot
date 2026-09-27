"""The support-OA handoff reply must survive the turn that produces it.

Production symptom (console, 2026-09-27): an employee writes on the TingTing
support OA, the console shows the handoff line ``Vui lòng chờ chuyên viên tư vấn
liên hệ.`` with the "Đã chặn" badge, and the employee receives NOTHING.

``_consultant_handoff`` runs inside the answer lane, i.e. BEFORE the turn
claims its send. The escalation it performs (``escalate_extracted_intent``) bumps
``conversations.version`` and clears ``bot_lock_owner`` — the two columns
``claim_send`` re-checks server-side — so the claim always lost and the drafted
reply was recorded SUPPRESSED instead of delivered.

These tests pin BOTH sides of the contract against the database:

1. the turn-owned escalation (``preserve_turn_ownership``, the handoff) leaves a
   claim that still wins, so the reply goes out;
2. the claim is not weakened — a newer inbound still loses it;
3. the post-send extraction escalation keeps its original semantics (it must
   release the lock and bump the version to invalidate stale writers).

The end-to-end turn is covered by the ``support-oa-handoff`` probe in
``scripts/smoke_turn.py``; this file pins the state-layer contract cheaply.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.graph.lanes import TINGTING_HANDOFF_REPLY, TINGTING_HANDOFF_REASON
from app.models.conversation import (
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.services.conversation.bot_path import ESCALATION_SYSTEM_NOTE
from app.services.conversation.state import ConversationState, utcnow
from tests.integration._conv_factory import make_zalo_conversation


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        return None

    async def conversation_updated(self, _conversation) -> None:
        return None


async def _seed(db) -> tuple[Conversation, Message, uuid.UUID]:
    """A support-OA thread pre-locked exactly as the webhook leaves it."""
    owner = uuid.uuid4()
    conv = await make_zalo_conversation(
        db,
        zalo_chat_id="support-handoff-claim",
        zalo_channel="oa",
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
async def test_support_handoff_keeps_its_own_turns_claim(integration_session) -> None:
    """The lane's escalation must not suppress the reply it is waiting to send."""
    conv, pending, owner = await _seed(integration_session)
    svc = ConversationState(integration_session, repo=None, events=_NoopEvents())
    version_at_start = conv.version

    assert await svc.escalate_extracted_intent(
        conv,
        reason=TINGTING_HANDOFF_REASON,
        confidence=1.0,
        expected_version=conv.version,
        preserve_turn_ownership=True,
    )

    await integration_session.refresh(conv)
    owned = await svc.claim_send(
        conv,
        version_at_start=version_at_start,
        lock_owner=owner,
        pending_message_id=pending.id,
        reply=TINGTING_HANDOFF_REPLY,
    )

    assert owned is True
    await integration_session.refresh(pending)
    assert pending.body == TINGTING_HANDOFF_REPLY
    assert pending.delivery_status == DeliveryStatus.SENDING
    # The handoff still reads as a handoff to a human.
    assert conv.mode == ConversationMode.HUMAN
    assert conv.needs_human is True
    notes = (
        await integration_session.scalars(
            select(Message.body).where(
                Message.conversation_id == conv.id,
                Message.sender == MessageSender.SYSTEM,
            )
        )
    ).all()
    assert list(notes) == [ESCALATION_SYSTEM_NOTE]


@pytest.mark.asyncio
async def test_turn_owned_escalation_still_loses_the_claim_to_a_newer_inbound(
    integration_session,
) -> None:
    """The preserved ownership is not a blanket exemption from the claim guard."""
    conv, pending, owner = await _seed(integration_session)
    svc = ConversationState(integration_session, repo=None, events=_NoopEvents())
    version_at_start = conv.version

    assert await svc.escalate_extracted_intent(
        conv,
        reason=TINGTING_HANDOFF_REASON,
        confidence=1.0,
        expected_version=conv.version,
        preserve_turn_ownership=True,
    )
    # A newer inbound lands between the lane and the claim.
    await svc.record_inbound(conv, body="Tôi cần hỗ trợ gấp")

    await integration_session.refresh(conv)
    owned = await svc.claim_send(
        conv,
        version_at_start=version_at_start,
        lock_owner=owner,
        pending_message_id=pending.id,
        reply=TINGTING_HANDOFF_REPLY,
    )

    assert owned is False


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
