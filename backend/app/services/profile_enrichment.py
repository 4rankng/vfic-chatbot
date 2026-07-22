"""Best-effort Zalo OA profile enrichment for canonical contacts.

The OA display name is channel profile data, not a confirmed candidate name.
It is therefore stored verbatim (apart from schema-safe text cleanup) on the
canonical ``Contact``.  The candidate extraction LLM separately decides
whether that display name is suitable evidence for ``Lead.name``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import ConversationService
from app.services.lead.events import LeadEventBus
from app.services.zalo_oa_service import OAUserProfile

logger = logging.getLogger(__name__)

_PROFILE_LOOKUP_DONE_TTL_SECONDS = 7 * 24 * 60 * 60
_PROFILE_LOOKUP_LOCK_TTL_SECONDS = 15
_PROFILE_LOOKUP_WAIT_SECONDS = 3.0
_CONTACT_DISPLAY_NAME_MAX_LENGTH = 160


def normalize_oa_profile_display_name(value: str | None) -> str:
    """Return schema-safe OA display text without judging whether it is a name."""
    display_name = re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", value or "")
    ).strip()
    return display_name[:_CONTACT_DISPLAY_NAME_MAX_LENGTH]


def _profile_lookup_keys(zalo_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(zalo_id.encode("utf-8")).hexdigest()[:32]
    return f"oa-profile:done:{digest}", f"oa-profile:lock:{digest}"


async def _claim_profile_lookup(
    zalo_id: str, *, wait_for_inflight: bool
) -> tuple[bool, str | None]:
    """Claim one OA lookup, coalescing inline and queued requests."""
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        done_key, lock_key = _profile_lookup_keys(zalo_id)
        deadline = time.monotonic() + (
            _PROFILE_LOOKUP_WAIT_SECONDS if wait_for_inflight else 0.0
        )
        while True:
            if await redis.exists(done_key):
                return False, None
            owner = uuid.uuid4().hex
            if await redis.set(
                lock_key,
                owner,
                nx=True,
                ex=_PROFILE_LOOKUP_LOCK_TTL_SECONDS,
            ):
                return True, owner
            if not wait_for_inflight or time.monotonic() >= deadline:
                return False, None
            await asyncio.sleep(0.1)
    except Exception:  # noqa: BLE001 -- Redis must never block enrichment
        return True, None


async def _mark_profile_lookup_done(zalo_id: str) -> None:
    try:
        from app.core.redis import get_redis

        done_key, _lock_key = _profile_lookup_keys(zalo_id)
        await get_redis().set(done_key, "1", ex=_PROFILE_LOOKUP_DONE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 -- cache is best-effort
        return


async def _release_profile_lookup(zalo_id: str, owner: str | None) -> None:
    if owner is None:
        return
    try:
        from app.core.redis import get_redis

        _done_key, lock_key = _profile_lookup_keys(zalo_id)
        redis = get_redis()
        if await redis.get(lock_key) == owner:
            await redis.delete(lock_key)
    except Exception:  # noqa: BLE001 -- lock expiry is the safety net
        return


class OAProfileLookup(Protocol):
    """Minimal user-detail capability required by profile enrichment."""

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None: ...


class ProfileEnrichmentService:
    """Fetch and persist an OA contact profile without classifying its name."""

    def __init__(self, db: AsyncSession, sender: OAProfileLookup) -> None:
        self.db = db
        self.sender = sender
        self._conversations = ConversationService(db)

    async def enrich_oa_user(
        self,
        zalo_id: str,
        *,
        user_id: str,
        wait_for_inflight: bool = False,
    ) -> bool:
        """Look up one OA user and persist contact display data if available."""
        conversation = await self._conversations.get_by_zalo(zalo_id)
        contact = conversation.contact if conversation is not None else None
        if contact is None:
            return False

        from app.models.lead import Lead

        leads = list(
            (
                await self.db.scalars(
                    select(Lead).where(Lead.contact_id == contact.id).order_by(Lead.id)
                )
            ).all()
        )
        if not leads:
            return False

        missing_display_name = not str(contact.display_name or "").strip()
        missing_contact_avatar = not str(contact.avatar_url or "").strip()
        missing_lead_avatar = any(not str(lead.avatar_url or "").strip() for lead in leads)
        if not (missing_display_name or missing_contact_avatar or missing_lead_avatar):
            return False

        claimed, lookup_owner = await _claim_profile_lookup(
            zalo_id, wait_for_inflight=wait_for_inflight
        )
        if not claimed:
            return False

        try:
            try:
                profile = await self.sender.get_user_detail(user_id)
            except Exception:  # noqa: BLE001 -- enrichment is best-effort
                logger.info("oa profile enrichment transport error")
                return False
            if profile is None:
                return False

            display_name = normalize_oa_profile_display_name(profile.display_name)
            avatar_url = (profile.avatar_url or "").strip()
            if not (display_name or avatar_url):
                return False

            if display_name and missing_display_name:
                contact.display_name = display_name
            if avatar_url and missing_contact_avatar:
                contact.avatar_url = avatar_url

            updated_leads = []
            if avatar_url:
                for lead in leads:
                    if not str(lead.avatar_url or "").strip():
                        lead.avatar_url = avatar_url
                        updated_leads.append(lead)

            await self.db.commit()
            complete = (
                bool(str(contact.display_name or "").strip())
                and bool(str(contact.avatar_url or "").strip())
                and all(bool(str(lead.avatar_url or "").strip()) for lead in leads)
            )
            if complete:
                await _mark_profile_lookup_done(zalo_id)
            logger.info(
                "oa profile enrichment applied avatar=%s display_name=%s complete=%s",
                bool(avatar_url and (missing_contact_avatar or updated_leads)),
                bool(display_name and missing_display_name),
                complete,
            )
            for saved_lead in updated_leads:
                try:
                    await LeadEventBus().lead_updated(saved_lead)
                except Exception:  # noqa: BLE001 -- realtime is best-effort
                    logger.info("oa profile enrichment realtime emit failed")
            return True
        finally:
            await _release_profile_lookup(zalo_id, lookup_owner)


__all__ = [
    "ProfileEnrichmentService",
    "OAUserProfile",
    "normalize_oa_profile_display_name",
]
