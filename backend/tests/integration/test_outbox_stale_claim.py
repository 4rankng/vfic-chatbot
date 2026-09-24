"""Stale-claim sweep behavior against the disposable Postgres database.

Replaces the source-text pins that used to read claim_stale_sending /
claim_stale_sending_unknown: which rows the sweeps select and terminalize is a
property of the executed UPDATE, not of the code's spelling.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import text

from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.models.outbox import OutboundOutbox, OutboxStatus
from app.services.outbox_service import claim_stale_sending, claim_stale_sending_unknown
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration

_STALE_AFTER_SECONDS = 720


async def _seed_message(db, *, tag: str) -> Message:
    conv = await make_zalo_conversation(
        db,
        zalo_chat_id=f"stale-claim-{tag}-{uuid.uuid4().hex[:10]}",
        bot_lock_owner=uuid.uuid4(),
        bot_locked_until=datetime.now(timezone.utc) + timedelta(seconds=120),
    )
    message = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body="Dạ em chào anh",
        delivery_status=DeliveryStatus.SENDING,
    )
    db.add(message)
    await db.flush()
    return message


async def _seed_outbox(db, *, message, status, age_seconds):
    row = OutboundOutbox(
        message_id=message.id,
        channel="zalo_bot",
        payload={"chat_id": "stale-claim", "text": message.body},
        status=status,
    )
    db.add(row)
    await db.flush()
    await db.execute(
        text(
            "UPDATE outbound_outbox SET updated_at = now() - INTERVAL '1 second' * :age "
            "WHERE id = :id"
        ),
        {"age": age_seconds, "id": row.id},
    )
    return row


async def _status_of(db, outbox_id):
    return (
        await db.execute(
            text("SELECT status FROM outbound_outbox WHERE id = :id"), {"id": outbox_id}
        )
    ).scalar_one()


async def test_stale_terminalize_only_touches_stale_sending_rows(integration_session):
    stale = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="stale"),
        status=OutboxStatus.SENDING.value,
        age_seconds=_STALE_AFTER_SECONDS + 60,
    )
    fresh = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="fresh"),
        status=OutboxStatus.SENDING.value,
        age_seconds=5,
    )
    sent = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="sent"),
        status=OutboxStatus.SENT.value,
        age_seconds=_STALE_AFTER_SECONDS + 60,
    )

    candidate = await claim_stale_sending_unknown(
        integration_session,
        outbox_id=stale.id,
        stale_after_seconds=_STALE_AFTER_SECONDS,
    )

    assert candidate is not None
    assert candidate.outbox_id == stale.id
    assert await _status_of(integration_session, stale.id) == "SEND_UNKNOWN"
    assert await _status_of(integration_session, fresh.id) == "SENDING"
    assert await _status_of(integration_session, sent.id) == "SENT"


async def test_stale_terminalize_never_touches_a_final_status_row(integration_session):
    row = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="sent-late"),
        status=OutboxStatus.SENT.value,
        age_seconds=_STALE_AFTER_SECONDS + 60,
    )

    candidate = await claim_stale_sending_unknown(
        integration_session,
        outbox_id=row.id,
        stale_after_seconds=_STALE_AFTER_SECONDS,
    )

    assert candidate is None
    assert await _status_of(integration_session, row.id) == "SENT"


async def test_redispatch_claims_only_stale_sending_and_skips_send_unknown(integration_session):
    stale_sending = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="redispatch-stale"),
        status=OutboxStatus.SENDING.value,
        age_seconds=_STALE_AFTER_SECONDS + 60,
    )
    unknown = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="redispatch-unknown"),
        status=OutboxStatus.SEND_UNKNOWN.value,
        age_seconds=_STALE_AFTER_SECONDS + 60,
    )
    fresh_sending = await _seed_outbox(
        integration_session,
        message=await _seed_message(integration_session, tag="redispatch-fresh"),
        status=OutboxStatus.SENDING.value,
        age_seconds=5,
    )

    claimed = await claim_stale_sending(
        integration_session,
        stale_threshold_seconds=_STALE_AFTER_SECONDS,
        batch_size=10,
    )

    claimed_ids = [c.outbox_id for c in claimed]
    assert stale_sending.id in claimed_ids
    assert unknown.id not in claimed_ids
    assert fresh_sending.id not in claimed_ids
