"""Regression: a seen/delivered receipt must advance an id-less SEND_UNKNOWN row.

Production bug: a message stamped SEND_UNKNOWN (transport timeout, stale SENDING,
or interrupted dispatch) carries NO ``zalo_message_id`` — the send failed before
Zalo returned one. ``apply_delivery_receipt_batch`` matched receipts only by
``zalo_message_id IN (ids)``, so a later ``user_seen_message`` receipt proving
the user actually saw the message matched nothing, and the row stayed
SEND_UNKNOWN forever — surfacing as the "Chưa xác nhận gửi" badge in the
recruiter console despite confirmed delivery.

These tests prove against a real database that:

1. An id-less SEND_UNKNOWN BOT message advances to READ on a seen receipt, even
   though the receipt's Zalo id matches no row by ``zalo_message_id`` (the
   reported bug). A PENDING placeholder with a NULL id is NOT touched.
2. The receipt path now emits ``message_created`` for each moved message (so the
   frontend delivery badge refreshes in realtime — previously only
   ``conversation_updated`` fired).
3. A normal SENT message with a recorded ``zalo_message_id`` still advances by
   id when the receipt carries that id (no regression on the primary match path;
   the id-match and SEND_UNKNOWN fallback fire together in one pass).
4. Forward-only: a DELIVERED receipt does not regress an already-READ row.
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
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


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
        conv = Conversation(
            zalo_chat_id=zalo_chat_id,
            mode=ConversationMode.BOT,
        )
        db.add(conv)
        await db.flush()
        conv_id = conv.id

        # The regression: transport timeout left no zalo_message_id. A later
        # user_seen receipt must still resolve this to READ.
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


async def test_seen_receipt_with_unknown_id_advances_only_id_less_send_unknown(
    integration_database: IntegrationDatabase,
) -> None:
    """The reported bug: a seen receipt resolves an id-less SEND_UNKNOWN row.

    The receipt's Zalo id matches no stored row, so only the SEND_UNKNOWN
    fallback advances a row. The PENDING placeholder (also id-less) is NOT
    touched (a receipt must never revive a never-sent row).
    """
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

        assert moved == 1  # only the id-less SEND_UNKNOWN fallback row

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            send_unknown = await db.get(Message, send_unknown_id)
            assert send_unknown is not None
            assert send_unknown.delivery_status == DeliveryStatus.READ

            # The PENDING placeholder must NOT be revived.
            pending = await db.get(Message, pending_id)
            assert pending is not None
            assert pending.delivery_status == DeliveryStatus.PENDING

        # The moved message emits message_created (realtime badge refresh), and
        # conversation_updated fires exactly once for the pass.
        assert {m.id for m in events.message_created_calls} == {send_unknown_id}
        assert len(events.conversation_updated_calls) == 1
    finally:
        await engine.dispose()


async def test_seen_receipt_advances_both_id_matched_and_send_unknown_rows(
    integration_database: IntegrationDatabase,
) -> None:
    """The id-match path and the SEND_UNKNOWN fallback fire together in one pass.

    The receipt carries the SENT row's Zalo id (advancing it via the primary
    path) AND the id-less SEND_UNKNOWN row advances via the fallback. Both
    moved rows emit message_created.
    """
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

        assert moved == 2  # id-matched SENT + fallback SEND_UNKNOWN

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            assert (await db.get(Message, send_unknown_id)).delivery_status == DeliveryStatus.READ
            assert (await db.get(Message, sent_id)).delivery_status == DeliveryStatus.READ

        assert {m.id for m in events.message_created_calls} == {send_unknown_id, sent_id}
    finally:
        await engine.dispose()


async def test_delivered_receipt_advances_id_less_send_unknown_to_delivered(
    integration_database: IntegrationDatabase,
) -> None:
    """A user_received receipt resolves an id-less SEND_UNKNOWN row to DELIVERED."""
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

        assert moved == 1  # only the id-less SEND_UNKNOWN fallback row

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            send_unknown = await db.get(Message, send_unknown_id)
            assert send_unknown is not None
            assert send_unknown.delivery_status == DeliveryStatus.DELIVERED
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
            # Pre-advance the SEND_UNKNOWN row to READ (as a prior seen receipt would).
            row = await db.get(Message, send_unknown_id)
            assert row is not None
            row.delivery_status = DeliveryStatus.READ
            await db.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conv = await db.get(Conversation, conv_id)
            assert conv is not None
            events = _RecordingEvents()
            moved = await ConversationState(db, repo=None, events=events).apply_delivery_receipt_batch(
                conv,
                zalo_message_ids=["zalo-id-not-stored"],
                delivered=True,
            )

        # The ex-SEND_UNKNOWN row is already READ, so the fallback query's
        # ``delivery_status == SEND_UNKNOWN`` filter excludes it. The id-match
        # path matches nothing. Nothing moves.
        assert moved == 0
        assert events.message_created_calls == []

        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            row = await db.get(Message, send_unknown_id)
            assert row is not None
            assert row.delivery_status == DeliveryStatus.READ
    finally:
        await engine.dispose()
