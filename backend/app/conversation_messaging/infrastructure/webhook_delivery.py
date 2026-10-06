"""Persistence adapters for provider-neutral webhook delivery events."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation_messaging.domain.statuses import DeliveryStatus
from app.models.contact import ContactChannelIdentity
from app.models.conversation import Conversation, Message
from app.services.conversation import ConversationService
from app.services.lead.interest import resolve_project_from_attribution


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
        message.delivery_status = DeliveryStatus.DELIVERED if delivered else DeliveryStatus.READ
    await db.commit()


async def apply_messenger_referral(
    db: AsyncSession, *, psid: str, account_key: str, attribution: dict
) -> None:
    """Record a thread's source when the referral carries no message.

    A new thread entered from an m.me link / Conversation ad / QR code delivers
    its ``ref`` in the Get Started **postback**, before the candidate types
    anything — there is no inbound row to carry that write. The conversation is
    ensured (idempotent, exactly what the first message would create) and the
    source stamped on it. Callers wrap this best-effort, like receipts.

    The dự án is resolved HERE, on this path specifically: the postback is the
    earliest touch a candidate produces, so resolving at the message boundary
    would leave every thread that entered via Get Started projectless until
    they typed — and a candidate who clicked an ad and never wrote would stay
    unattributed forever. Resolution is best-effort by contract: a catalog
    problem must never fail the webhook ack.
    """
    if not psid or not attribution:
        return
    service = ConversationService(db)
    conversation = await service.ensure_by_identity(
        provider="facebook_messenger",
        account_key=account_key,
        external_id=psid,
        zalo_chat_id_alias=None,
        zalo_channel_alias="facebook_messenger",
    )
    if not attribution.get("project_id"):
        project_id = await resolve_project_from_attribution(db, attribution)
        if project_id:
            attribution = {**attribution, "project_id": project_id}
    await service.stamp_attribution(conversation, attribution)


async def enqueue_facebook_turn(
    db: AsyncSession,
    outcome,
    runtime_authority,
    *,
    enqueue: Callable[[dict[str, Any]], bool | None],
) -> None:
    persisted = outcome.message
    if persisted is None:
        return
    conversation = await db.scalar(
        select(Conversation).where(Conversation.id == uuid.UUID(persisted.conversation_id))
    )
    if conversation is None:
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
        "user_text": persisted.body,
        "user_name": "",
        "reply_to_message_id": persisted.provider_message_id,
        "lock_owner": str(lock_owner),
        "execution_source": "queued",
        "received_at": (persisted.created_at.isoformat() if persisted.created_at else ""),
        "received_at_epoch": time.time(),
        "trace_id": "",
        "runtime_revision_id": (
            str(runtime_authority.revision_id) if runtime_authority is not None else ""
        ),
        "authority_generation": (
            runtime_authority.authority_generation if runtime_authority is not None else None
        ),
        "runtime_fingerprint": (
            runtime_authority.fingerprint if runtime_authority is not None else ""
        ),
    }
    try:
        accepted = enqueue(job)
    except Exception:
        await service.release_lock(conversation, lock_owner=lock_owner)
        raise
    if accepted is False:
        await service.release_lock(conversation, lock_owner=lock_owner)
