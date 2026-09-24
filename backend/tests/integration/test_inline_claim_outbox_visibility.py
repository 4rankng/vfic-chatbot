"""REL-06: the inline turn's outbound command is claimed in the claim transaction.

Behavioral proof against a real PostgreSQL: while the inline send runs, the
command is SENDING — so the 60 s dispatcher sweep (which selects PENDING rows
with no age gate) can never win it and record a false ERROR turn for a message
it delivered instead. The inline sender then resumes its own claim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.models.outbox import OutboundOutbox, OutboxStatus
from app.services.conversation.state import ConversationState
from app.services.outbox_service import (
    DispatchResult,
    dispatch_message_outbox,
    pending_outbox_ids,
)
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration


async def _claimed_turn(db: AsyncSession):
    """A conversation whose per-chat lock is live, with a pending BOT row."""
    owner = uuid.uuid4()
    conv = await make_zalo_conversation(
        db,
        zalo_chat_id=f"inline-claim-{uuid.uuid4().hex[:10]}",
        bot_lock_owner=owner,
        bot_locked_until=datetime.now(timezone.utc) + timedelta(seconds=120),
    )
    pending = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body="Đang soạn trả lời...",
        delivery_status=DeliveryStatus.PENDING,
    )
    db.add(pending)
    await db.flush()
    return conv, pending, owner


async def test_inline_send_claims_the_command_before_provider_io(
    integration_session: AsyncSession,
) -> None:
    """The command is SENDING from the claim commit, so the sweep cannot see it."""
    conv, pending, owner = await _claimed_turn(integration_session)
    state = ConversationState(integration_session, SimpleNamespace(), SimpleNamespace())

    claimed = await state.claim_send(
        conv,
        version_at_start=conv.version,
        lock_owner=owner,
        pending_message_id=pending.id,
        reply="Dạ em chào anh",
        outbox_channel="zalo_bot",
        outbox_payload={"chat_id": conv.zalo_chat_id, "text": "Dạ em chào anh"},
    )

    assert claimed is True
    outbox = (
        await integration_session.scalars(
            select(OutboundOutbox).where(OutboundOutbox.message_id == pending.id)
        )
    ).one()
    assert outbox.status == OutboxStatus.SENDING.value
    # The dispatcher's own selection: the row is invisible while the inline send runs.
    assert await pending_outbox_ids(integration_session) == []


async def test_inline_sender_resumes_its_own_claim(
    integration_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claimed command is sent inline — not refused as unavailable."""
    from app.services import outbox_service

    conv, pending, owner = await _claimed_turn(integration_session)
    state = ConversationState(integration_session, SimpleNamespace(), SimpleNamespace())
    assert await state.claim_send(
        conv,
        version_at_start=conv.version,
        lock_owner=owner,
        pending_message_id=pending.id,
        reply="Dạ em chào anh",
        outbox_channel="zalo_bot",
        outbox_payload={"chat_id": conv.zalo_chat_id, "text": "Dạ em chào anh"},
    )

    dispatched: list[int] = []

    async def fake_provider_dispatch(_db, candidate, _outbox, _cfg, _settings, _oa_refresh):
        dispatched.append(candidate.message_id)
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=True,
            provider_message_id="mid-1",
        )

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", fake_provider_dispatch)

    result = await dispatch_message_outbox(integration_session, message_id=pending.id)

    assert result is not None and result.ok
    assert result.msg_id == "mid-1"
    assert dispatched == [pending.id]
