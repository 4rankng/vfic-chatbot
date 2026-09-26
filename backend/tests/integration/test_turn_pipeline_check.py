"""Integration coverage for the turn-pipeline stall detector's SQL.

These pin the two queries that the 2026-09-26 post-flip gate relies on, and —
just as importantly — the false positives that must NOT fail a deploy:

  * a BOT-mode conversation whose newest inbound has no reply is a stall;
  * a BOT-mode conversation with a reply after the inbound is not;
  * a conversation with an in-flight turn (open ``bot_runs`` row started after
    the inbound) is not a stall — it is being worked on;
  * a HUMAN-mode conversation is not a stall — the bot is silent by design;
  * a ``PENDING`` outbound row is a stall only once it is older than the
    dispatch tolerance; recent ``PENDING`` and terminal rows are not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.conversation_messaging.domain.statuses import (
    BotRunOutcome,
    ConversationMode,
    DeliveryStatus,
    MessageSender,
)
from app.models.conversation import BotRun, Message
from app.models.outbox import OutboxStatus, OutboundOutbox
from scripts.turn_pipeline_check import _stale_pending, _stalled_conversations
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration

WINDOW_SECONDS = 300
STALE_AFTER_SECONDS = 120


async def _add_message(
    db,
    *,
    conversation,
    sender: MessageSender,
    body: str,
    age_seconds: int = 0,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        sender=sender,
        body=body,
        delivery_status=DeliveryStatus.SENT,
        created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
    )
    db.add(message)
    await db.flush()
    return message


async def test_flags_bot_conversation_without_a_reply(integration_session) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-no-reply",
        mode=ConversationMode.BOT,
    )
    await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.WORKER,
        body="chị ở thái bình",
        age_seconds=60,
    )
    await integration_session.commit()

    stalled = await _stalled_conversations(integration_session, WINDOW_SECONDS)

    assert [conv_id for conv_id, _ in stalled] == [str(conversation.id)]


async def test_accepts_bot_conversation_with_a_reply(integration_session) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-answered",
        mode=ConversationMode.BOT,
    )
    await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.WORKER,
        body="chị ở thái bình",
        age_seconds=90,
    )
    await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.BOT,
        body="Dạ chị ơi",
        age_seconds=30,
    )
    await integration_session.commit()

    stalled = await _stalled_conversations(integration_session, WINDOW_SECONDS)

    assert stalled == []


async def test_accepts_conversation_with_an_in_flight_turn(integration_session) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-in-flight",
        mode=ConversationMode.BOT,
    )
    inbound = await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.WORKER,
        body="hello",
        age_seconds=45,
    )
    integration_session.add(
        BotRun(
            conversation_id=conversation.id,
            version_at_start=1,
            outcome=BotRunOutcome.SENT,
            started_at=inbound.created_at + timedelta(seconds=5),
            ended_at=None,
        )
    )
    await integration_session.commit()

    stalled = await _stalled_conversations(integration_session, WINDOW_SECONDS)

    assert stalled == []


async def test_ignores_conversations_the_bot_must_not_answer(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-human-mode",
        mode=ConversationMode.HUMAN,
    )
    await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.WORKER,
        body="hello",
        age_seconds=60,
    )
    await integration_session.commit()

    stalled = await _stalled_conversations(integration_session, WINDOW_SECONDS)

    assert stalled == []


async def test_ignores_inbound_outside_the_window(integration_session) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-stale-inbound",
        mode=ConversationMode.BOT,
    )
    await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.WORKER,
        body="old message",
        age_seconds=WINDOW_SECONDS + 120,
    )
    await integration_session.commit()

    stalled = await _stalled_conversations(integration_session, WINDOW_SECONDS)

    assert stalled == []


async def test_flags_only_old_pending_outbound_rows(integration_session) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="pipeline-outbox",
        mode=ConversationMode.BOT,
    )
    chat_id = str(conversation.zalo_chat_id)

    old_pending = await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.BOT,
        body="stuck",
        age_seconds=STALE_AFTER_SECONDS + 60,
    )
    recent_pending = await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.BOT,
        body="just queued",
        age_seconds=5,
    )
    old_sent = await _add_message(
        integration_session,
        conversation=conversation,
        sender=MessageSender.BOT,
        body="already sent",
        age_seconds=STALE_AFTER_SECONDS + 60,
    )
    for message, status in (
        (old_pending, OutboxStatus.PENDING),
        (recent_pending, OutboxStatus.PENDING),
        (old_sent, OutboxStatus.SENT),
    ):
        outbox = OutboundOutbox(
            message_id=message.id,
            channel="zalo_bot",
            payload={"chat_id": chat_id, "text": message.body},
            status=status.value,
            created_at=message.created_at,
        )
        integration_session.add(outbox)
        if message is old_pending:
            stuck_outbox = outbox
    await integration_session.commit()

    stale = await _stale_pending(integration_session, STALE_AFTER_SECONDS)

    assert [outbox_id for outbox_id, _ in stale] == [stuck_outbox.id]
