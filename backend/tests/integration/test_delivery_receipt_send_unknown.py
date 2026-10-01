"""Real PostgreSQL regressions for truthful delivery receipts.

Only exact provider message IDs can correlate a receipt with a stored send.
Id-less uncertainty stays SEND_UNKNOWN, and a receipt for an accepted prefix
cannot acknowledge an incomplete logical answer. Matched complete sends still
advance, emit realtime events, and never regress an already-READ row.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.conversation import (
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.services.conversation.state import ConversationState
from app.channels import types as ct
from app.channels.dispatch import ChannelDispatchService
from app.channels.registry import ChannelAdapterRegistry
from app.services.outbox_service import create_pending_outbox
from tests.integration.conftest import IntegrationDatabase
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("sender", [MessageSender.BOT, MessageSender.RECRUITER])
@pytest.mark.parametrize("seen", [False, True])
@pytest.mark.parametrize("matches_known_message", [False, True])
async def test_unrelated_receipt_never_confirms_idless_unknown_sends(
    integration_session, sender, seen, matches_known_message,
) -> None:
    """A real receipt for one message cannot acknowledge other uncertain sends."""
    db = integration_session
    conv = await make_zalo_conversation(
        db, zalo_chat_id=f"unrelated-{sender.value}-{seen}-{matches_known_message}",
    )
    unknown = [Message(
        conversation_id=conv.id, sender=sender, body=f"uncertain send {index}",
        delivery_status=DeliveryStatus.SEND_UNKNOWN,
    ) for index in range(2)]
    known = Message(
        conversation_id=conv.id, sender=sender, body="known accepted message",
        delivery_status=DeliveryStatus.SENT, zalo_message_id="known-receipt-id",
    )
    db.add_all([*unknown, known])
    await db.commit()
    version_before = conv.version
    unread_before = conv.unread_count
    events = _RecordingEvents()
    moved = await ConversationState(db, repo=None, events=events).apply_delivery_receipt_batch(
        conv,
        zalo_message_ids=["known-receipt-id" if matches_known_message else "unmatched-receipt-id"],
        delivered=not seen, seen=seen,
    )
    for message in unknown:
        await db.refresh(message)
        assert message.delivery_status == DeliveryStatus.SEND_UNKNOWN
    await db.refresh(known)
    assert moved == int(matches_known_message)
    assert known.delivery_status == (
        (DeliveryStatus.READ if seen else DeliveryStatus.DELIVERED)
        if matches_known_message else DeliveryStatus.SENT
    )
    assert [message.id for message in events.message_created_calls] == (
        [known.id] if matches_known_message else []
    )
    assert len(events.conversation_updated_calls) == int(matches_known_message)
    assert conv.version == version_before
    assert conv.unread_count == unread_before


@pytest.mark.parametrize("sender", [MessageSender.BOT, MessageSender.RECRUITER])
@pytest.mark.parametrize("seen", [False, True])
@pytest.mark.parametrize("accepted_id", [None, "accepted-prefix"])
async def test_partial_answer_receipt_cannot_acknowledge_undelivered_tail(
    integration_session, sender, seen, accepted_id,
) -> None:
    """Real dispatch→persist→receipt keeps a partial logical answer unknown."""
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    db = integration_session
    conv = await make_zalo_conversation(db, zalo_chat_id=f"partial-{sender.value}-{seen}-{accepted_id}")
    text = "Dự án có trong danh mục đã xác minh. " * 200
    pending = Message(
        conversation_id=conv.id, sender=sender, body=text,
        delivery_status=DeliveryStatus.PENDING,
    )
    ordinary = Message(
        conversation_id=conv.id, sender=sender, body="single request awaiting an acknowledgment",
        delivery_status=DeliveryStatus.SEND_UNKNOWN, zalo_message_id="single-request-id",
    )
    db.add_all([pending, ordinary])
    await db.flush()
    outbox = await create_pending_outbox(
        db, message_id=pending.id, channel=ct.PROVIDER_ZALO_OA,
        payload={"chat_id": "candidate", "text": text},
    )
    await db.commit()
    adapter = SimpleNamespace(
        provider=ct.PROVIDER_ZALO_OA,
        send_text=AsyncMock(side_effect=[
            ct.ChannelSendResult(ok=True, provider_message_id=accepted_id),
            ct.ChannelSendResult(ok=False, error="rejected tail", error_class="provider_error"),
        ]),
    )
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    result = await ChannelDispatchService(registry).send(ct.OutboundTextCommand(
        provider=ct.PROVIDER_ZALO_OA, account_key="default:zalo_oa",
        recipient_id="candidate", text=text, channel_account_generation=1,
    ))
    assert result.is_send_unknown
    assert adapter.send_text.await_count == 2
    events = _RecordingEvents()
    state = ConversationState(db, repo=None, events=events)
    finalize = (
        state.finalize_outbound_dispatch
        if sender == MessageSender.BOT
        else state.finalize_recruiter_delivery
    )
    await finalize(
        conv, message_id=pending.id, outbox_id=outbox.id, delivered=False,
        zalo_message_id=result.provider_message_id,
        external_error=result.error, error_class=result.error_class,
    )
    events.message_created_calls.clear()
    moved = await state.apply_delivery_receipt_batch(
        conv, zalo_message_ids=[accepted_id or "unmatched-id", "single-request-id"],
        delivered=not seen, seen=seen,
    )
    await db.refresh(pending)
    await db.refresh(outbox)
    await db.refresh(ordinary)
    assert pending.delivery_status == DeliveryStatus.SEND_UNKNOWN
    assert outbox.status == "SEND_UNKNOWN"
    assert pending.provider_message_id == accepted_id
    assert pending.external_error == result.error
    assert ordinary.delivery_status == (DeliveryStatus.READ if seen else DeliveryStatus.DELIVERED)
    assert moved == 1
    assert [msg.id for msg in events.message_created_calls] == [ordinary.id]


class _RecordingEvents:
    """Captures message_created / conversation_updated calls for assertions."""

    def __init__(self) -> None:
        self.message_created_calls: list[Message] = []
        self.conversation_updated_calls: list[Conversation] = []

    async def message_created(self, message, _conversation) -> None:
        self.message_created_calls.append(message)

    async def conversation_updated(self, conversation) -> None:
        self.conversation_updated_calls.append(conversation)


async def _seed(engine, *, zalo_chat_id: str) -> tuple[int, int, int, int]:
    """Create a conversation with three BOT messages exercising each code path.

    Returns (conv_id, send_unknown_msg_id, sent_msg_id, pending_msg_id).
    """
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        conv = await make_zalo_conversation(
            db,
            zalo_chat_id=zalo_chat_id,
            zalo_channel="bot",
            mode=ConversationMode.BOT,
        )
        conv_id = conv.id

        # A timeout left no provider id; unrelated receipts cannot confirm it.
        send_unknown = Message(
            conversation_id=conv_id,
            sender=MessageSender.BOT,
            body="reply whose send timed out (no zalo id)",
            delivery_status=DeliveryStatus.SEND_UNKNOWN,
            zalo_message_id=None,
        )
        # A normal confirmed send — the primary id-match path must still advance it.
        sent = Message(
            conversation_id=conv_id,
            sender=MessageSender.BOT,
            body="reply Zalo acknowledged",
            delivery_status=DeliveryStatus.SENT,
            zalo_message_id="zalo-sent-1",
        )
        # A pre-send placeholder — a receipt must NOT revive a never-sent row.
        pending = Message(
            conversation_id=conv_id,
            sender=MessageSender.BOT,
            body="Đang soạn trả lời...",
            delivery_status=DeliveryStatus.PENDING,
            zalo_message_id=None,
        )
        db.add_all([send_unknown, sent, pending])
        await db.commit()
        return conv_id, send_unknown.id, sent.id, pending.id


async def test_seen_receipt_with_unknown_id_preserves_uncorrelated_send(
    integration_database: IntegrationDatabase,
) -> None:
    """An unmatched receipt proves nothing about an id-less uncertain send."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, send_unknown_id, _sent_id, pending_id = await _seed(
        engine, zalo_chat_id="receipt-send-unknown-seen"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            events = _RecordingEvents()
            # The receipt carries a Zalo id that matches nothing in our DB.
            moved = await ConversationState(db, repo=None, events=events).apply_delivery_receipt_batch(
                conv,
                zalo_message_ids=["zalo-id-not-stored-anywhere"],
                seen=True,
            )

        assert moved == 0

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            send_unknown = await db.get(Message, send_unknown_id)
            assert send_unknown is not None
            assert send_unknown.delivery_status == DeliveryStatus.SEND_UNKNOWN

            # The PENDING placeholder must NOT be revived.
            pending = await db.get(Message, pending_id)
            assert pending is not None
            assert pending.delivery_status == DeliveryStatus.PENDING

        assert events.message_created_calls == []
        assert events.conversation_updated_calls == []
    finally:
        await engine.dispose()


async def test_seen_receipt_advances_only_the_id_matched_message(
    integration_database: IntegrationDatabase,
) -> None:
    """A known send advances without changing another uncertain send."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, send_unknown_id, sent_id, _pending_id = await _seed(
        engine, zalo_chat_id="receipt-both-paths"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            events = _RecordingEvents()
            moved = await ConversationState(db, repo=None, events=events).apply_delivery_receipt_batch(
                conv,
                zalo_message_ids=["zalo-sent-1"],
                seen=True,
            )

        assert moved == 1

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            assert (await db.get(Message, send_unknown_id)).delivery_status == DeliveryStatus.SEND_UNKNOWN
            assert (await db.get(Message, sent_id)).delivery_status == DeliveryStatus.READ

        assert {m.id for m in events.message_created_calls} == {sent_id}
        assert len(events.conversation_updated_calls) == 1
    finally:
        await engine.dispose()


async def test_delivered_receipt_preserves_idless_uncertainty(
    integration_database: IntegrationDatabase,
) -> None:
    """An unmatched user_received receipt does not establish delivery."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, send_unknown_id, _sent_id, _pending_id = await _seed(
        engine, zalo_chat_id="receipt-send-unknown-delivered"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            moved = await ConversationState(
                db, repo=None, events=_RecordingEvents()
            ).apply_delivery_receipt_batch(
                conv,
                zalo_message_ids=["zalo-id-not-stored"],
                delivered=True,
            )

        assert moved == 0

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            send_unknown = await db.get(Message, send_unknown_id)
            assert send_unknown is not None
            assert send_unknown.delivery_status == DeliveryStatus.SEND_UNKNOWN
    finally:
        await engine.dispose()


async def test_delivered_receipt_does_not_regress_an_already_read_row(
    integration_database: IntegrationDatabase,
) -> None:
    """Forward-only: a DELIVERED receipt (rank 2) must not regress a READ row (rank 3)."""
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    conv_id, send_unknown_id, _sent_id, _pending_id = await _seed(
        engine, zalo_chat_id="receipt-already-read"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            # A prior exact-id seen receipt already acknowledged this message.
            row = await db.get(Message, send_unknown_id)
            assert row is not None
            row.delivery_status = DeliveryStatus.READ
            row.zalo_message_id = "already-read-id"
            await db.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            events = _RecordingEvents()
            moved = await ConversationState(db, repo=None, events=events).apply_delivery_receipt_batch(
                conv,
                zalo_message_ids=["already-read-id"],
                delivered=True,
            )

        # The exact matched message is already READ, so nothing regresses.
        assert moved == 0
        assert events.message_created_calls == []

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            row = await db.get(Message, send_unknown_id)
            assert row is not None
            assert row.delivery_status == DeliveryStatus.READ
    finally:
        await engine.dispose()
