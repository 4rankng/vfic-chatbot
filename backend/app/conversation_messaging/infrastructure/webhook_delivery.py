"""Persistence adapters for provider-neutral webhook delivery events."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.composition.conversation_messaging import enqueue_chat_turn
from app.conversation_messaging.domain.statuses import DeliveryStatus
from app.models.contact import ContactChannelIdentity
from app.models.conversation import Conversation, Message
from app.services.conversation import ConversationService


async def apply_messenger_receipt(db: AsyncSession, receipt, account_key: str) -> None:
    if not receipt.provider_message_ids:
        return
    rows = (
        await db.scalars(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            )
            .where(
                Message.provider_message_id.in_(receipt.provider_message_ids),
                Message.sender.in_(("BOT", "RECRUITER")),
                ContactChannelIdentity.provider == receipt.provider,
                ContactChannelIdentity.account_key == account_key,
            )
        )
    ).all()
    delivered = receipt.kind == "delivered"
    rank = {DeliveryStatus.SENT: 1, DeliveryStatus.DELIVERED: 2, DeliveryStatus.READ: 3}
    target_rank = 2 if delivered else 3
    for message in rows:
        current_rank = rank.get(message.delivery_status, 0)
        if current_rank >= target_rank or current_rank == 0:
            continue
        message.delivery_status = (
            DeliveryStatus.DELIVERED if delivered else DeliveryStatus.READ
        )
    await db.commit()


async def enqueue_facebook_turn(db: AsyncSession, outcome, runtime_authority) -> None:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == uuid.UUID(outcome.conversation_id)
        )
    )
    if conversation is None:
        return
    last_inbound = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
    ).first()
    if last_inbound is None:
        return
    service = ConversationService(db)
    conversation = await service.get(conversation.id)
    if conversation is None or not service.run_start_guard(conversation):
        return
    version_at_start = conversation.version
    lock_owner = await service.acquire_lock(conversation.id)
    if lock_owner is None:
        return
    job = {
        "v": 2,
        "conversation_id": str(conversation.id),
        "version_at_start": version_at_start,
        "user_text": last_inbound.body,
        "user_name": "",
        "reply_to_message_id": last_inbound.provider_message_id or "",
        "lock_owner": str(lock_owner),
        "execution_source": "queued",
        "received_at": (
            last_inbound.created_at.isoformat() if last_inbound.created_at else ""
        ),
        "received_at_epoch": time.time(),
        "trace_id": "",
        "runtime_revision_id": (
            str(runtime_authority.revision_id) if runtime_authority is not None else ""
        ),
        "authority_generation": (
            runtime_authority.authority_generation
            if runtime_authority is not None
            else None
        ),
        "runtime_fingerprint": (
            runtime_authority.fingerprint if runtime_authority is not None else ""
        ),
    }
    try:
        accepted = enqueue_chat_turn(job)
    except Exception:
        await service.release_lock(conversation, lock_owner=lock_owner)
        raise
    if accepted is False:
        await service.release_lock(conversation, lock_owner=lock_owner)

