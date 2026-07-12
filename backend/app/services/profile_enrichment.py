"""Best-effort Zalo OA profile enrichment for leads.

Fetches ``display_name`` + avatar from Zalo's OA user-detail endpoint and
persists them onto an existing lead. Designed to run off the webhook hot path
(low-priority RQ job) so the sub-second acknowledgement budget is preserved.

Contract:
- Never raises on Zalo/transport errors — logs structured, non-PII context and
  returns. The UI keeps the initials fallback.
- Short-circuits when the lead already has an ``avatar_url``, so repeat
  messages don't cause unbounded Zalo lookups.
- Supplements a missing lead name from ``display_name`` but never overwrites a
  non-empty name (recruiter/candidate-provided names win).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lead.events import LeadEventBus
from app.services.lead.repository import LeadRepository
from app.services.zalo_oa_service import OAUserProfile, ZaloOASender

logger = logging.getLogger(__name__)

# Only patch name/avatar; never touches stage, score, recruiter, notes, etc.
_ENRICH_SQL = text(
    """
    UPDATE leads SET
        avatar_url = COALESCE(NULLIF(:avatar_url, ''), leads.avatar_url),
        name = COALESCE(NULLIF(leads.name, ''), NULLIF(:display_name, '')),
        updated_at = now()
    WHERE zalo_id = :zalo_id
      AND (
          leads.avatar_url IS NULL
          OR leads.avatar_url = ''
          OR leads.name IS NULL
          OR leads.name = ''
      )
    """
)


class ProfileEnrichmentService:
    """Best-effort OA profile lookup + lead avatar/name persistence."""

    def __init__(self, db: AsyncSession, sender: ZaloOASender) -> None:
        self.db = db
        self.sender = sender
        self._leads = LeadRepository(db)

    async def enrich_oa_user(self, zalo_id: str, *, user_id: str) -> bool:
        """Look up one OA user and persist avatar/name if missing.

        ``zalo_id`` is the conversation-scoped id (``oa:<user_id>``) used as the
        Lead unique key. ``user_id`` is the external OA user id passed to Zalo's
        user-detail API. Returns True when a profile was fetched and applied.
        """
        # Short-circuit: if the lead already has an avatar AND a name, there is
        # nothing to add — avoid unbounded Zalo lookups on every inbound message.
        existing = await self._leads.by_zalo_id(zalo_id)
        if existing is None:
            return False
        if existing.get("avatar_url") and existing.get("name"):
            return False

        try:
            profile = await self.sender.get_user_detail(user_id)
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            logger.info("oa profile enrichment transport error zalo_id=%s", zalo_id)
            return False
        if profile is None or not (profile.avatar_url or profile.display_name):
            return False

        await self.db.execute(
            _ENRICH_SQL,
            {
                "zalo_id": zalo_id,
                "avatar_url": profile.avatar_url,
                "display_name": profile.display_name,
            },
        )
        await self.db.commit()
        logger.info(
            "oa profile enrichment applied zalo_id=%s avatar=%s name=%s",
            zalo_id,
            bool(profile.avatar_url),
            bool(profile.display_name),
        )
        # Emit lead.updated so an open conversation header/chat-thread refreshes
        # the avatar in realtime. Mirrors candidate_extraction.upsert_lead. The
        # realtime publish is best-effort: a Socket.IO/Redis outage must not
        # fail the already-committed enrichment.
        try:
            from app.models.lead import Lead

            saved = await self.db.get(Lead, existing["id"])
            if saved is not None:
                await LeadEventBus().lead_updated(saved)
        except Exception:  # noqa: BLE001 — realtime is best-effort
            logger.info("oa profile enrichment realtime emit failed zalo_id=%s", zalo_id)
        return True


__all__ = ["ProfileEnrichmentService", "OAUserProfile"]
