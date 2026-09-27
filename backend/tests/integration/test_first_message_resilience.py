"""First-message resilience: the 2026-09-28 silent-first-message outage.

Three coordinated regressions, one user-visible symptom (the FIRST message a
user sends is never answered; every later message works):

1. ``ensure_by_identity`` created the conversation in memory; the first
   message's realtime events serialized it and the lazy load of
   ``channel_identity`` outside the async greenlet raised MissingGreenlet —
   500ing the webhook AFTER the inbound was committed.
2. Zalo's redelivery (past the 8s dedup window) hit
   ``uq_messages_conv_provider_message`` and 500'd forever, so ingress could
   never recover the message.
3. Any post-commit event failure would have 500'd the webhook even though the
   inbound is durable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.conversation import Message
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.state import ConversationState

PROVIDER = "zalo_oa"
ACCOUNT = "tingting"


class _ExplodingEvents:
    """Event bus whose publishes fail — realtime is bookkeeping, not delivery."""

    async def message_created(self, _message, _conversation) -> None:
        raise RuntimeError("redis down")

    async def conversation_updated(self, _conversation) -> None:
        raise RuntimeError("redis down")


class _RecordingEvents:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0

    async def message_created(self, _message, _conversation) -> None:
        self.created += 1

    async def conversation_updated(self, _conversation) -> None:
        self.updated += 1


@pytest.mark.asyncio
async def test_created_conversation_carries_loaded_relationships(integration_session) -> None:
    """The create path must not return a conversation that lazy-loads on serialize."""
    state = ConversationState(integration_session, ConversationRepository(integration_session), _RecordingEvents())
    conv = await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id="first-msg-user",
        zalo_chat_id_alias="oa:tingting:first-msg-user",
        zalo_channel_alias="oa",
    )
    # The realtime payload reads these relationships; an unloaded attribute
    # means a lazy load, which outside the async greenlet is the outage.
    assert "channel_identity" in conv.__dict__
    assert "contact" in conv.__dict__


@pytest.mark.asyncio
async def test_duplicate_inbound_redelivery_returns_the_existing_row(integration_session) -> None:
    state = ConversationState(integration_session, ConversationRepository(integration_session), _RecordingEvents())
    conv = await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id="redelivery-user",
        zalo_chat_id_alias="oa:tingting:redelivery-user",
        zalo_channel_alias="oa",
    )
    first = await state.record_inbound(
        conv, body="Tôi mới dùng phần mềm này", zalo_message_id="msg-6ca8496d"
    )
    version_after_first = conv.version

    second = await state.record_inbound(
        conv, body="Tôi mới dùng phần mềm này", zalo_message_id="msg-6ca8496d"
    )

    assert second.id == first.id
    rows = (
        await integration_session.scalars(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conv.id)
        )
    ).one()
    assert rows == 1
    # The duplicate delivery performs none of the original's writes.
    assert conv.version == version_after_first


@pytest.mark.asyncio
async def test_inbound_event_failure_keeps_the_message_durable(integration_session) -> None:
    state = ConversationState(integration_session, ConversationRepository(integration_session), _ExplodingEvents())
    conv = await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id="event-failure-user",
        zalo_chat_id_alias="oa:tingting:event-failure-user",
        zalo_channel_alias="oa",
    )
    msg = await state.record_inbound(
        conv,
        body="không biết tên đăng nhập của mình là gì",
        zalo_message_id="msg-event-failure",
    )
    assert msg.id is not None
    stored = await integration_session.get(Message, msg.id)
    assert stored is not None
    assert stored.body.endswith("tên đăng nhập của mình là gì")
