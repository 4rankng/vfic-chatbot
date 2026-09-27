"""Conversation fixture: 25 Zalo threads, each with its canonical Contact."""

from __future__ import annotations

from datetime import timedelta

from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.user import User

from .common import days_ago, hours_ago, new_uuid, rng


def make_conversations(
    users: list[User],
) -> tuple[list[Conversation], list[Contact], list[ContactChannelIdentity]]:
    """Build 25 conversations, each with its canonical Contact + channel identity.

    Alembic 0047 made ``conversations.contact_id`` / ``channel_identity_id``
    mandatory: every thread hangs off exactly one ``Contact`` and one
    ``ContactChannelIdentity``. Mirror ``ConversationState.ensure_by_identity``
    (the production create path) against the seeded ACTIVE Zalo-bot account so
    the threads resolve exactly like real inbound webhooks.

    Returns ``(conversations, contacts, identities)`` — the caller inserts
    contacts and identities first (FK order).
    """
    convos: list[Conversation] = []
    contacts: list[Contact] = []
    identities: list[ContactChannelIdentity] = []
    modes = [
        ConversationMode.BOT,
        ConversationMode.BOT,
        ConversationMode.BOT,
        ConversationMode.HUMAN,
        ConversationMode.SEMI_AUTO,
        ConversationMode.CLOSED,
    ]

    for i in range(25):
        mode = modes[i % len(modes)]
        status = (
            ConversationStatus.CLOSED
            if mode == ConversationMode.CLOSED
            else ConversationStatus.OPEN
        )
        created = days_ago(rng.randint(0, 14))
        assigned = (
            users[1 + (i % 2)].id
            if mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO)
            else None
        )
        zalo_chat_id = f"zalo_conv_seed_{i:04d}"
        contact = Contact(id=new_uuid())
        identity = ContactChannelIdentity(
            id=new_uuid(),
            contact_id=contact.id,
            provider="zalo_bot",
            account_key="default:zalo_bot",  # seeded ACTIVE zalo_bot channel account
            external_id=zalo_chat_id,
        )
        contacts.append(contact)
        identities.append(identity)

        convos.append(
            Conversation(
                id=new_uuid(),
                zalo_chat_id=zalo_chat_id,
                contact_id=contact.id,
                channel_identity_id=identity.id,
                mode=mode,
                status=status,
                needs_human=mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO),
                version=1 + rng.randint(0, 2),
                assigned_recruiter_id=assigned,
                unread_count=rng.randint(0, 5) if mode != ConversationMode.CLOSED else 0,
                last_inbound_at=hours_ago(-rng.randint(-72, -1)),
                last_outbound_at=hours_ago(-rng.randint(1, 48)),
                created_at=created,
                updated_at=created + timedelta(hours=rng.randint(1, 72)),
            )
        )
    return convos, contacts, identities
