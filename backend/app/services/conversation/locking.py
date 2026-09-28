"""Per-chat bot mutex: acquire, release, renew, and stale-lock recovery.

The lock lives in the ``conversations`` row's ``bot_lock_*`` trio and is mutated
with conditional SQL, so this family is pure model-state logic with no
dependency on the send path. Mixed into ``BotConversationState``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid
from datetime import timedelta

from sqlalchemy import or_, update

from app.conversation_messaging.domain.ownership import (
    normalize_lock_owner as _normalize_lock_owner,
)
from app.core.config import get_settings
from app.models.conversation import Conversation, ConversationMode
from app.services.conversation._shared import affected_rows, utcnow



if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class LockingMixin:
    """Per-chat mutex lifecycle for the bot-send path."""

    # Assigned by the composing state class. Declared so ``self.db``
    # resolves here — the mixin reads it but never owns it.
    db: AsyncSession

    async def acquire_lock(
        self,
        conv_id: uuid.UUID,
        ttl_seconds: int | None = None,
        lock_owner: uuid.UUID | str | None = None,
    ) -> uuid.UUID | None:
        """Per-chat mutex via bot_locked_until. Atomic: only one run holds it at a time.

        TTL defaults to settings.bot_lock_ttl_seconds, which is sized to exceed the
        worst-case single turn (a worker crash mid-turn is recovered by TTL expiry;
        the owner token makes stale jobs unable to clear a newer job's lock).
        """
        ttl = ttl_seconds if ttl_seconds is not None else get_settings().bot_lock_ttl_seconds
        now = utcnow()
        locked_until = now + timedelta(seconds=ttl)
        owner = _normalize_lock_owner(lock_owner) or uuid.uuid4()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.mode.in_((ConversationMode.BOT, ConversationMode.SEMI_AUTO)),
                or_(
                    Conversation.bot_locked_until.is_(None),
                    Conversation.bot_locked_until < utcnow(),
                ),
            )
            .values(
                bot_locked_until=locked_until,
                bot_lock_owner=owner,
                bot_lock_heartbeat_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return owner if affected_rows(res) == 1 else None

    async def release_lock(
        self, conv: Conversation, lock_owner: uuid.UUID | str | None = None
    ) -> None:
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None
            await self.db.commit()
            return

        res = await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conv.id, Conversation.bot_lock_owner == owner)
            .values(
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if affected_rows(res) == 1:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None

    async def renew_lock(
        self, conv_id: uuid.UUID, *, lock_owner: uuid.UUID | str, ttl_seconds: int | None = None
    ) -> bool:
        """Renew a live turn's lease only when it still owns the lock."""
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            return False
        ttl = ttl_seconds if ttl_seconds is not None else get_settings().bot_lock_ttl_seconds
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.bot_lock_owner == owner,
                Conversation.bot_locked_until > now,
            )
            .values(
                bot_locked_until=now + timedelta(seconds=ttl),
                bot_lock_heartbeat_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return affected_rows(res) == 1

    async def break_stale_lock(self, conv_id: uuid.UUID, *, stale_after_seconds: int) -> bool:
        """Force-clear a per-chat mutex whose owner heartbeat is stale (older than
        ``stale_after_seconds``), so a crashed/killed worker does not stall the
        conversation until ``bot_lock_ttl`` expires.

        Conditional on heartbeat age: a live, actively-processing turn has a
        fresh heartbeat (set at ``acquire_lock``; a normal turn finishes well
        inside ``chat_turn_job_timeout``) and is never stolen. Only a wedged job
        whose heartbeat predates the RQ kill threshold qualifies. Safe to compose
        with ``claim_send``: a not-yet-reaped old turn that reaches its send
        after its lock was stolen fails the claim's ``lock_owner`` guard and
        suppresses rather than double-sending. Returns True iff a stale lock was
        cleared.
        """
        cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.bot_locked_until.is_not(None),
                or_(
                    Conversation.bot_lock_heartbeat_at.is_(None),
                    Conversation.bot_lock_heartbeat_at < cutoff,
                ),
            )
            .values(
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return affected_rows(res) == 1
