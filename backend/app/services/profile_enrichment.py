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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.services.conversation import ConversationService
from app.services.lead.events import LeadEventBus
from app.services.zalo_oa_service import OAUserProfile

logger = logging.getLogger(__name__)

_PROFILE_LOOKUP_DONE_TTL_SECONDS = 7 * 24 * 60 * 60
_PROFILE_LOOKUP_LOCK_TTL_SECONDS = 15
_PROFILE_LOOKUP_WAIT_SECONDS = 3.0
_CONTACT_DISPLAY_NAME_MAX_LENGTH = 160
_MESSENGER_PROFILE_NAMESPACE = "messenger-profile"
# The only gender values that may reach the prompt as an address form.
_PROFILE_GENDERS = frozenset({"male", "female"})


def normalize_oa_profile_display_name(value: str | None) -> str:
    """Return schema-safe OA display text without judging whether it is a name."""
    display_name = re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", value or "")
    ).strip()
    return display_name[:_CONTACT_DISPLAY_NAME_MAX_LENGTH]


def _profile_lookup_keys(external_id: str, *, namespace: str = "oa-profile") -> tuple[str, str]:
    """Return the (done, lock) Redis keys for one provider identity.

    ``namespace`` keeps each provider's coalescing state separate so a Zalo and
    a Messenger identity that happen to share an id string cannot mask each
    other's lookups.
    """
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:32]
    return f"{namespace}:done:{digest}", f"{namespace}:lock:{digest}"


def _is_blank(value: str | None) -> bool:
    return not str(value or "").strip()


def _blank_column(column):
    return func.nullif(func.trim(column), "").is_(None)


async def _claim_profile_lookup(
    external_id: str,
    *,
    wait_for_inflight: bool,
    ignore_done: bool = False,
    namespace: str = "oa-profile",
) -> tuple[bool, str | None]:
    """Claim one profile lookup, coalescing inline and queued requests."""
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        done_key, lock_key = _profile_lookup_keys(external_id, namespace=namespace)
        deadline = time.monotonic() + (
            _PROFILE_LOOKUP_WAIT_SECONDS if wait_for_inflight else 0.0
        )
        while True:
            if not ignore_done and await redis.exists(done_key):
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


async def _mark_profile_lookup_done(
    external_id: str, *, namespace: str = "oa-profile"
) -> None:
    try:
        from app.core.redis import get_redis

        done_key, _lock_key = _profile_lookup_keys(external_id, namespace=namespace)
        await get_redis().set(done_key, "1", ex=_PROFILE_LOOKUP_DONE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 -- cache is best-effort
        return


async def _release_profile_lookup(
    external_id: str, owner: str | None, *, namespace: str = "oa-profile"
) -> None:
    if owner is None:
        return
    try:
        from app.core.redis import get_redis

        _done_key, lock_key = _profile_lookup_keys(external_id, namespace=namespace)
        redis = get_redis()
        if await redis.get(lock_key) == owner:
            await redis.delete(lock_key)
    except Exception:  # noqa: BLE001 -- lock expiry is the safety net
        return


class OAProfileLookup(Protocol):
    """Minimal user-detail capability required by profile enrichment."""

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None: ...


class MessengerProfile(Protocol):
    """The Messenger profile shape this service reads."""

    display_name: str
    profile_pic: str
    gender: str


class MessengerProfileLookup(Protocol):
    """Fetch one Messenger profile by PSID, or ``None`` when unavailable."""

    async def __call__(self, psid: str) -> MessengerProfile | None: ...


class ProfileEnrichmentService:
    """Fetch and persist an OA contact profile without classifying its name."""

    def __init__(self, db: AsyncSession, sender: OAProfileLookup | None = None) -> None:
        """``sender`` is the Zalo OA lookup. Messenger enrichment injects its
        own fetch callable per call and leaves this unset."""
        self.db = db
        self.sender = sender
        self._conversations = ConversationService(db)

    async def _select_contact(
        self,
        contact_id,
        *,
        populate_existing: bool = False,
    ) -> Contact | None:
        return await self.db.scalar(
            select(Contact)
            .where(Contact.id == contact_id)
            .execution_options(populate_existing=populate_existing)
        )

    async def _select_leads(
        self,
        contact_id,
        *,
        populate_existing: bool = False,
    ) -> list:
        from app.models.lead import Lead

        return list(
            (
                await self.db.scalars(
                    select(Lead)
                    .where(Lead.contact_id == contact_id)
                    .order_by(Lead.id)
                    .execution_options(populate_existing=populate_existing)
                )
            ).all()
        )

    async def _set_contact_display_name_if_blank(
        self,
        contact_id,
        display_name: str,
    ) -> bool:
        result = await self.db.execute(
            update(Contact)
            .where(
                Contact.id == contact_id,
                _blank_column(Contact.display_name),
            )
            .values(display_name=display_name)
            .returning(Contact.id)
        )
        return result.scalar_one_or_none() is not None

    async def _set_contact_avatar_if_blank(
        self,
        contact_id,
        avatar_url: str,
    ) -> bool:
        result = await self.db.execute(
            update(Contact)
            .where(
                Contact.id == contact_id,
                _blank_column(Contact.avatar_url),
            )
            .values(avatar_url=avatar_url)
            .returning(Contact.id)
        )
        return result.scalar_one_or_none() is not None

    async def _set_lead_avatars_if_blank(
        self,
        contact_id,
        avatar_url: str,
    ) -> list[int]:
        from app.models.lead import Lead

        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.contact_id == contact_id,
                _blank_column(Lead.avatar_url),
            )
            .values(avatar_url=avatar_url)
            .returning(Lead.id)
        )
        return list(result.scalars().all())

    async def _set_lead_genders_if_blank(
        self,
        contact_id,
        gender: str,
    ) -> list[int]:
        """Write provider gender onto every lead that has none.

        Blank-only by design: a gender the candidate stated themselves is
        stronger evidence than the Facebook profile field and must never be
        overwritten by it.
        """
        from app.models.lead import Lead

        result = await self.db.execute(
            update(Lead)
            .where(
                Lead.contact_id == contact_id,
                _blank_column(Lead.gender),
            )
            .values(gender=gender)
            .returning(Lead.id)
        )
        return list(result.scalars().all())

    async def enrich_oa_user(
        self,
        zalo_id: str,
        *,
        user_id: str,
        wait_for_inflight: bool = False,
        force_lookup: bool = False,
    ) -> bool:
        """Look up one OA user and persist contact display data if available."""
        conversation = await self._conversations.get_by_zalo(zalo_id)
        contact = conversation.contact if conversation is not None else None
        if contact is None:
            return False

        leads = await self._select_leads(contact.id)
        if not leads:
            return False

        missing_display_name = _is_blank(contact.display_name)
        missing_contact_avatar = _is_blank(contact.avatar_url)
        missing_lead_avatar = any(_is_blank(lead.avatar_url) for lead in leads)
        if not (missing_display_name or missing_contact_avatar or missing_lead_avatar):
            return False

        claimed, lookup_owner = await _claim_profile_lookup(
            zalo_id,
            wait_for_inflight=wait_for_inflight,
            ignore_done=force_lookup,
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

            contact_display_name_updated = False
            contact_avatar_updated = False
            updated_lead_ids: list[int] = []
            updated_leads = []
            updated_any = False

            if display_name and missing_display_name:
                contact_display_name_updated = (
                    await self._set_contact_display_name_if_blank(contact.id, display_name)
                )
                updated_any = updated_any or contact_display_name_updated
            if avatar_url:
                if missing_contact_avatar:
                    contact_avatar_updated = await self._set_contact_avatar_if_blank(
                        contact.id,
                        avatar_url,
                    )
                    updated_any = updated_any or contact_avatar_updated
                updated_lead_ids = await self._set_lead_avatars_if_blank(contact.id, avatar_url)
                updated_any = updated_any or bool(updated_lead_ids)

            if updated_any:
                await self.db.commit()
            fresh_contact = await self._select_contact(contact.id, populate_existing=True)
            fresh_leads = await self._select_leads(contact.id, populate_existing=True)
            if updated_lead_ids:
                updated_leads_by_id = {lead.id: lead for lead in fresh_leads}
                updated_leads = [
                    updated_leads_by_id[lead_id]
                    for lead_id in updated_lead_ids
                    if lead_id in updated_leads_by_id
                ]
            complete = (
                fresh_contact is not None
                and not _is_blank(fresh_contact.display_name)
                and not _is_blank(fresh_contact.avatar_url)
                and bool(fresh_leads)
                and all(not _is_blank(lead.avatar_url) for lead in fresh_leads)
            )
            if complete:
                await _mark_profile_lookup_done(zalo_id)
            logger.info(
                "oa profile enrichment applied avatar=%s display_name=%s complete=%s",
                bool(contact_avatar_updated or updated_lead_ids),
                contact_display_name_updated,
                complete,
            )
            for saved_lead in updated_leads:
                try:
                    await LeadEventBus().lead_updated(saved_lead)
                except Exception:  # noqa: BLE001 -- realtime is best-effort
                    logger.info("oa profile enrichment realtime emit failed")
            return updated_any
        finally:
            await _release_profile_lookup(zalo_id, lookup_owner)


    async def enrich_messenger_user(
        self,
        psid: str,
        *,
        page_id: str,
        fetch_profile: MessengerProfileLookup,
        wait_for_inflight: bool = False,
        force_lookup: bool = False,
    ) -> bool:
        """Look up one Messenger user and persist display data + gender.

        ``fetch_profile`` is injected rather than imported so this service keeps
        depending on a capability instead of the Facebook provider module.

        Gender is what makes the Vietnamese address form (anh / chị) possible.
        It is frequently absent — the field needs both App Review approval and a
        per-Page grant, and Meta omits it for people who have not made it public
        — so an absent gender is a normal outcome here, not a failure. The
        prompt layer addresses those candidates neutrally.
        """
        conversation = await self._conversations.get_by_identity(
            provider="facebook_messenger",
            account_key=page_id,
            external_id=psid,
        )
        contact = conversation.contact if conversation is not None else None
        if contact is None:
            return False

        leads = await self._select_leads(contact.id)
        if not leads:
            return False

        missing_display_name = _is_blank(contact.display_name)
        missing_contact_avatar = _is_blank(contact.avatar_url)
        missing_lead_avatar = any(_is_blank(lead.avatar_url) for lead in leads)
        missing_lead_gender = any(_is_blank(lead.gender) for lead in leads)
        if not (
            missing_display_name
            or missing_contact_avatar
            or missing_lead_avatar
            or missing_lead_gender
        ):
            return False

        claimed, lookup_owner = await _claim_profile_lookup(
            psid,
            wait_for_inflight=wait_for_inflight,
            ignore_done=force_lookup,
            namespace=_MESSENGER_PROFILE_NAMESPACE,
        )
        if not claimed:
            return False

        try:
            try:
                profile = await fetch_profile(psid)
            except Exception:  # noqa: BLE001 -- enrichment is best-effort
                logger.info("messenger profile enrichment transport error")
                return False
            if profile is None:
                return False

            display_name = normalize_oa_profile_display_name(profile.display_name)
            avatar_url = (profile.profile_pic or "").strip()
            gender = (profile.gender or "").strip().lower()
            if gender not in _PROFILE_GENDERS:
                gender = ""
            if not (display_name or avatar_url or gender):
                return False

            display_name_updated = False
            avatar_updated = False
            updated_lead_ids: list[int] = []
            gender_lead_ids: list[int] = []
            updated_any = False

            if display_name and missing_display_name:
                display_name_updated = await self._set_contact_display_name_if_blank(
                    contact.id, display_name
                )
                updated_any = updated_any or display_name_updated
            if avatar_url:
                if missing_contact_avatar:
                    avatar_updated = await self._set_contact_avatar_if_blank(
                        contact.id, avatar_url
                    )
                    updated_any = updated_any or avatar_updated
                updated_lead_ids = await self._set_lead_avatars_if_blank(
                    contact.id, avatar_url
                )
                updated_any = updated_any or bool(updated_lead_ids)
            if gender:
                gender_lead_ids = await self._set_lead_genders_if_blank(contact.id, gender)
                updated_any = updated_any or bool(gender_lead_ids)

            if updated_any:
                await self.db.commit()
            fresh_contact = await self._select_contact(contact.id, populate_existing=True)
            fresh_leads = await self._select_leads(contact.id, populate_existing=True)

            # Settled means "Meta has told us everything it is willing to tell
            # us about this person". A field Meta omitted stays blank forever
            # under the current grants, so re-asking on every inbound message
            # would burn a Graph call per turn for nothing. The done key's TTL
            # still retries weekly, which is what picks up a newly-approved
            # permission or a profile the person later made public.
            settled = (
                fresh_contact is not None
                and bool(fresh_leads)
                and (not _is_blank(fresh_contact.display_name) or not display_name)
                and (not _is_blank(fresh_contact.avatar_url) or not avatar_url)
                and (
                    all(not _is_blank(lead.avatar_url) for lead in fresh_leads)
                    or not avatar_url
                )
                and (
                    all(not _is_blank(lead.gender) for lead in fresh_leads)
                    or not gender
                )
            )
            if settled:
                await _mark_profile_lookup_done(
                    psid, namespace=_MESSENGER_PROFILE_NAMESPACE
                )
            logger.info(
                "messenger profile enrichment applied avatar=%s display_name=%s "
                "gender=%s settled=%s",
                bool(avatar_updated or updated_lead_ids),
                display_name_updated,
                bool(gender_lead_ids),
                settled,
            )

            touched_lead_ids = set(updated_lead_ids) | set(gender_lead_ids)
            if touched_lead_ids:
                leads_by_id = {lead.id: lead for lead in fresh_leads}
                for lead_id in sorted(touched_lead_ids):
                    saved_lead = leads_by_id.get(lead_id)
                    if saved_lead is None:
                        continue
                    try:
                        await LeadEventBus().lead_updated(saved_lead)
                    except Exception:  # noqa: BLE001 -- realtime is best-effort
                        logger.info("messenger profile enrichment realtime emit failed")
            return updated_any
        finally:
            await _release_profile_lookup(
                psid, lookup_owner, namespace=_MESSENGER_PROFILE_NAMESPACE
            )


__all__ = [
    "ProfileEnrichmentService",
    "MessengerProfileLookup",
    "OAUserProfile",
    "normalize_oa_profile_display_name",
]
