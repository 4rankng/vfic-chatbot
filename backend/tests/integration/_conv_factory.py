"""Shared integration-test helpers for creating conversations with canonical identity.

After Alembic 0047, ``conversations.contact_id`` and ``channel_identity_id`` are
NOT NULL, so integration tests can no longer construct a ``Conversation`` row
directly. These helpers create the required Contact + ContactChannelIdentity +
Conversation in one go, mirroring what ``ConversationState.ensure_by_identity``
does in production.

Tests that previously did ``Conversation(zalo_chat_id=..., ...)`` should call
:func:`make_zalo_conversation` instead, passing the extra kwargs (mode,
bot_lock_owner, etc.) through.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation


async def make_conversation(
    db: AsyncSession,
    *,
    provider: str,
    account_key: str,
    external_id: str,
    zalo_chat_id: str | None = None,
    zalo_channel: str = "bot",
    **conversation_kwargs: Any,
) -> Conversation:
    """Create (or reuse) a Contact + identity + Conversation for the neutral triple.

    Idempotent on the identity triple: a second call for the same triple reuses
    the existing Contact/identity and creates a NEW conversation (callers that
    want get-or-create semantics should query first). Extra kwargs are passed
    straight to the ``Conversation`` constructor (mode, bot_lock_owner, etc.).
    """
    identity = (
        await db.scalars(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.provider == provider,
                ContactChannelIdentity.account_key == account_key,
                ContactChannelIdentity.external_id == external_id,
            )
        )
    ).first()
    if identity is None:
        contact = Contact()
        db.add(contact)
        await db.flush()
        identity = ContactChannelIdentity(
            contact_id=contact.id,
            provider=provider,
            account_key=account_key,
            external_id=external_id,
        )
        db.add(identity)
        await db.flush()

    conv = Conversation(
        zalo_chat_id=zalo_chat_id,
        zalo_channel=zalo_channel,
        contact_id=identity.contact_id,
        channel_identity_id=identity.id,
        **conversation_kwargs,
    )
    db.add(conv)
    await db.flush()
    return conv


async def make_zalo_conversation(
    db: AsyncSession,
    *,
    zalo_chat_id: str,
    zalo_channel: str = "bot",
    **conversation_kwargs: Any,
) -> Conversation:
    """Zalo-flavored convenience wrapper.

    Maps the Zalo (channel, chat_id) to the neutral triple using the stable
    synthetic account keys backfilled by Alembic 0047, and strips the ``oa:``
    storage prefix for OA — matching ``ConversationState.ensure``.
    """
    if zalo_channel == "oa":
        provider = "zalo_oa"
        account_key = "default:zalo_oa"
        external_id = (
            zalo_chat_id.removeprefix("oa:")
            if zalo_chat_id.startswith("oa:")
            else zalo_chat_id
        )
    else:
        provider = "zalo_bot"
        account_key = "default:zalo_bot"
        external_id = zalo_chat_id
    return await make_conversation(
        db,
        provider=provider,
        account_key=account_key,
        external_id=external_id,
        zalo_chat_id=zalo_chat_id,
        zalo_channel=zalo_channel,
        **conversation_kwargs,
    )


def _anon_external_id() -> str:
    """A fresh external id for tests that don't care about identity specifics."""
    return f"test-{uuid.uuid4().hex[:12]}"


__all__ = ["make_conversation", "make_zalo_conversation"]
