"""Integration coverage for the smoke persistence invariant helper."""

from __future__ import annotations

import pytest

from app.models.conversation import ConversationMode, DeliveryStatus, Message, MessageSender
from app.models.outbox import OutboxStatus, OutboundOutbox
from scripts.smoke_turn import _assert_persisted_delivery_invariant
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration


async def test_smoke_invariant_accepts_one_terminal_message_and_matching_outbox(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-success",
        mode=ConversationMode.BOT,
    )
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id="provider-1",
        provider_message_id="provider-1",
        external_error=None,
    )
    integration_session.add(message)
    await integration_session.flush()
    integration_session.add(
        OutboundOutbox(
            message_id=message.id,
            channel="zalo_bot",
            payload={"chat_id": conversation.zalo_chat_id, "text": message.body},
            status=OutboxStatus.SENT.value,
            zalo_message_id="provider-1",
            provider_message_id="provider-1",
        )
    )
    await integration_session.commit()

    await _assert_persisted_delivery_invariant(
        integration_session,
        conv_id=conversation.id,
        message_id=message.id,
        expected_reply=message.body,
    )


async def test_smoke_invariant_rejects_duplicate_or_residual_bot_rows(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-duplicate",
        mode=ConversationMode.BOT,
    )
    sent_message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id="provider-sent",
        provider_message_id="provider-sent",
    )
    residual_pending = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Dang soan tra loi...",
        delivery_status=DeliveryStatus.PENDING,
        zalo_message_id=None,
        provider_message_id=None,
    )
    integration_session.add_all([sent_message, residual_pending])
    await integration_session.flush()
    integration_session.add(
        OutboundOutbox(
            message_id=sent_message.id,
            channel="zalo_bot",
            payload={"chat_id": conversation.zalo_chat_id, "text": sent_message.body},
            status=OutboxStatus.SENT.value,
            zalo_message_id="provider-sent",
            provider_message_id="provider-sent",
        )
    )
    await integration_session.commit()

    with pytest.raises(AssertionError, match="expected exactly one BOT message"):
        await _assert_persisted_delivery_invariant(
            integration_session,
            conv_id=conversation.id,
            message_id=sent_message.id,
            expected_reply=sent_message.body,
        )


async def test_smoke_invariant_rejects_pending_message_id_mismatch(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-id-mismatch",
        mode=ConversationMode.BOT,
    )
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id="provider-2",
        provider_message_id="provider-2",
    )
    integration_session.add(message)
    await integration_session.flush()
    integration_session.add(
        OutboundOutbox(
            message_id=message.id,
            channel="zalo_bot",
            payload={"chat_id": conversation.zalo_chat_id, "text": message.body},
            status=OutboxStatus.SENT.value,
            zalo_message_id="provider-2",
            provider_message_id="provider-2",
        )
    )
    await integration_session.commit()

    with pytest.raises(AssertionError, match="did not match pending_message_id"):
        await _assert_persisted_delivery_invariant(
            integration_session,
            conv_id=conversation.id,
            message_id=message.id + 1,
            expected_reply=message.body,
        )


async def test_smoke_invariant_rejects_missing_outbox(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-missing-outbox",
        mode=ConversationMode.BOT,
    )
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id="provider-3",
        provider_message_id="provider-3",
    )
    integration_session.add(message)
    await integration_session.commit()

    with pytest.raises(AssertionError, match="expected exactly one outbound_outbox row"):
        await _assert_persisted_delivery_invariant(
            integration_session,
            conv_id=conversation.id,
            message_id=message.id,
            expected_reply=message.body,
        )


async def test_smoke_invariant_rejects_non_sent_state_or_retained_error(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-non-sent",
        mode=ConversationMode.BOT,
    )
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SEND_UNKNOWN,
        zalo_message_id="provider-4",
        provider_message_id="provider-4",
        external_error="timed out",
    )
    integration_session.add(message)
    await integration_session.flush()
    integration_session.add(
        OutboundOutbox(
            message_id=message.id,
            channel="zalo_bot",
            payload={"chat_id": conversation.zalo_chat_id, "text": message.body},
            status=OutboxStatus.SEND_UNKNOWN.value,
            zalo_message_id="provider-4",
            provider_message_id="provider-4",
        )
    )
    await integration_session.commit()

    with pytest.raises(AssertionError, match="expected SENT"):
        await _assert_persisted_delivery_invariant(
            integration_session,
            conv_id=conversation.id,
            message_id=message.id,
            expected_reply=message.body,
        )


async def test_smoke_invariant_rejects_provider_id_mismatch(
    integration_session,
) -> None:
    conversation = await make_zalo_conversation(
        integration_session,
        zalo_chat_id="smoke-invariant-provider-mismatch",
        mode=ConversationMode.BOT,
    )
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.BOT,
        body="Kiem tra trien khai thanh cong.",
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id="legacy-id",
        provider_message_id="canonical-id",
    )
    integration_session.add(message)
    await integration_session.flush()
    integration_session.add(
        OutboundOutbox(
            message_id=message.id,
            channel="zalo_bot",
            payload={"chat_id": conversation.zalo_chat_id, "text": message.body},
            status=OutboxStatus.SENT.value,
            zalo_message_id="legacy-id",
            provider_message_id="canonical-id",
        )
    )
    await integration_session.commit()

    with pytest.raises(AssertionError, match="did not match zalo_message_id"):
        await _assert_persisted_delivery_invariant(
            integration_session,
            conv_id=conversation.id,
            message_id=message.id,
            expected_reply=message.body,
        )
