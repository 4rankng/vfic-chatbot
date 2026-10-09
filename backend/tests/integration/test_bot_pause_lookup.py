"""Real-query regression tests for the per-account bot pause lookup.

The unit suites stub ``state.bot_paused``, so the real lookup's result
handling shipped unexercised on 2026-10-09: it read its SQLAlchemy 2.x
``Row`` through ``isinstance(row, (tuple, list))``, which is always False
(Row is not a tuple subclass in SQLAlchemy 2.x), and the pause therefore
failed open in production on every channel. These tests drive the real
query end to end against the disposable database so an actual Row flows
through the check.
"""

from __future__ import annotations

import pytest

from app.models.channel_account import ChannelAccount
from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation

pytestmark = pytest.mark.integration


async def _seed_conversation(
    db,
    *,
    account_key: str,
    bot_paused: bool,
    account_status: str = "ACTIVE",
) -> Conversation:
    """Insert account + identity + conversation; return the conversation."""
    contact = Contact(display_name="Pause Regression")
    db.add(contact)
    await db.flush()
    identity = ContactChannelIdentity(
        contact_id=contact.id,
        provider="facebook_messenger",
        account_key=account_key,
        external_id=f"psid-{account_key}",
    )
    db.add(identity)
    await db.flush()
    if account_status is not None:
        db.add(
            ChannelAccount(
                provider="facebook_messenger",
                account_key=account_key,
                label=f"Page {account_key}",
                status=account_status,
                bot_paused=bot_paused,
            )
        )
    conversation = Conversation(
        contact_id=contact.id,
        channel_identity_id=identity.id,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _bot_paused(db, conversation: Conversation) -> bool:
    from app.services.conversation.service import ConversationService

    service = ConversationService(db)
    return await service.bot_paused(conversation)


async def test_paused_active_account_reports_paused(integration_database):
    """The regression: a real Row from a paused ACTIVE account reads True."""
    from app.core.db import async_session

    async with async_session() as db:
        conversation = await _seed_conversation(
            db, account_key="111", bot_paused=True
        )
        assert await _bot_paused(db, conversation) is True


async def test_unpaused_active_account_reports_not_paused(integration_database):
    from app.core.db import async_session

    async with async_session() as db:
        conversation = await _seed_conversation(
            db, account_key="222", bot_paused=False
        )
        assert await _bot_paused(db, conversation) is False


async def test_inactive_account_reports_not_paused(integration_database):
    """A disconnected Page (INACTIVE) never pauses, flag or not."""
    from app.core.db import async_session

    async with async_session() as db:
        conversation = await _seed_conversation(
            db, account_key="333", bot_paused=True, account_status="INACTIVE"
        )
        assert await _bot_paused(db, conversation) is False


async def test_identity_without_account_row_reports_not_paused(integration_database):
    """No channel account for the identity's key: fail open, not paused."""
    from app.core.db import async_session

    async with async_session() as db:
        conversation = await _seed_conversation(
            db, account_key="444", bot_paused=True, account_status=None
        )
        assert await _bot_paused(db, conversation) is False
