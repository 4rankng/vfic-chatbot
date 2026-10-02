"""Regression: stale-outbox finalization must not steal a live turn's lock.

Production bug (2026-07-15, conversation 5c3aa51e): the outbound dispatch
recovery sweep finalized a prior turn's stale outbox row (msg 439, SEND_UNKNOWN)
while a NEWER turn (254, replying to Thúy) held the conversation's bot lock.
``finalize_outbound_dispatch`` cleared ``bot_lock_owner``/``bot_locked_until``
unconditionally, so the in-flight turn's ``claim_send`` guard evaluated false
and the reply was SUPPRESSED — surfaced as the suppressed badge in the console.

These tests prove the conditional lock-clear invariant against a real database:

1. A live lock held by an in-flight turn survives finalization of a stale BOT
   message (the regression — previously the lock was wiped).
2. An expired/crashed turn's lock is still cleared (the original intent of the
   branch — don't regress the recovery path).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.conversation import (
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.outbox import OutboundOutbox, OutboxStatus
from app.services.conversation.state import ConversationState, utcnow
from tests.integration.conftest import IntegrationDatabase
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        return None

    async def conversation_updated(self, _conversation) -> None:
        return None


async def _seed(engine, *, zalo_chat_id: str) -> tuple[int, int]:
    """Create a conversation + a stale SENDING outbox row for a BOT message."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        owner = uuid.uuid4()
        conv = await make_zalo_conversation(
            db,
            zalo_chat_id=zalo_chat_id,
            zalo_channel="bot",
            mode=ConversationMode.BOT,
            bot_lock_owner=owner,
            bot_locked_until=utcnow() + timedelta(seconds=180),
            bot_lock_heartbeat_at=utcnow(),
        )
        conv_id = conv.id

        msg = Message(
            conversation_id=conv_id,
            sender=MessageSender.BOT,
            body="prior reply whose dispatch never got a receipt",
            delivery_status=DeliveryStatus.SENDING,
        )
        db.add(msg)
        await db.flush()
        msg_id = msg.id

        db.add(
            OutboundOutbox(
                message_id=msg_id,
                channel="zalo_oa",
                payload={"text": "prior reply"},
                status=OutboxStatus.SENDING.value,
                attempts=1,
            )
        )
        await db.commit()
        return conv_id, msg_id


async def test_finalize_does_not_clear_a_live_lock_held_by_an_in_flight_turn(
    integration_database: IntegrationDatabase,
) -> None:
    """The regression: finalizing a stale row must leave a live lock intact."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, msg_id = await _seed(engine, zalo_chat_id="finalize-lock-race-live")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            live_owner = conv.bot_lock_owner
            live_until = conv.bot_locked_until
            assert live_owner is not None
            assert live_until is not None

            await ConversationState(db, repo=None, events=_NoopEvents()).finalize_outbound_dispatch(
                conv,
                message_id=msg_id,
                outbox_id=await _outbox_id(db, msg_id),
                delivered=False,
                external_error="outbound dispatch interrupted before receipt",
                error_class="unknown",
            )

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            # The in-flight turn's lock must survive (this was the bug).
            assert conv.bot_lock_owner == live_owner
            assert conv.bot_locked_until == live_until
            assert conv.bot_lock_heartbeat_at is not None
            # The stale message + outbox row were still terminalized correctly.
            msg = await db.get(Message, msg_id)
            assert msg is not None
            assert msg.delivery_status == DeliveryStatus.SEND_UNKNOWN
    finally:
        await engine.dispose()


async def test_finalize_still_clears_an_expired_crashed_turn_lock(
    integration_database: IntegrationDatabase,
) -> None:
    """Original intent: a crashed turn's expired lock is still released."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, msg_id = await _seed(engine, zalo_chat_id="finalize-lock-race-expired")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            # Expire the lock so it is no longer "live" — as if the owning turn
            # crashed and the TTL elapsed before the recovery sweep finalized it.
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            conv.bot_locked_until = utcnow() - timedelta(seconds=1)
            await db.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            await ConversationState(db, repo=None, events=_NoopEvents()).finalize_outbound_dispatch(
                conv,
                message_id=msg_id,
                outbox_id=await _outbox_id(db, msg_id),
                delivered=False,
                external_error="outbound dispatch interrupted before receipt",
                error_class="unknown",
            )

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            assert conv.bot_lock_owner is None
            assert conv.bot_locked_until is None
            assert conv.bot_lock_heartbeat_at is None
    finally:
        await engine.dispose()


async def _outbox_id(db, msg_id: int) -> int:
    from sqlalchemy import select

    row = await db.scalar(
        select(OutboundOutbox.id).where(OutboundOutbox.message_id == msg_id)
    )
    assert row is not None
    return int(row)
