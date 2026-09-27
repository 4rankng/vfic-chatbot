"""Zalo OA account resolver + link lifecycle (multi-OA).

The original OA is the ``default:zalo_oa`` channel account Alembic 0047 seeded:
it keeps the singleton ``zalo_oa_*`` credentials and is the fallback for every
event the router cannot attribute. Each additional OA is another ``zalo_oa``
channel account whose ``account_key`` is its Zalo OA id, with its own four
credentials under ``zalo_oa_*:<oa id>`` (see :class:`ZaloSettingsMixin`).

Inbound routing keys on the ``oa_id`` Zalo puts in the webhook body. An absent
or unknown id resolves to the default account, so a payload-shape change or an
unlinked OA degrades to today's single-OA behaviour instead of dropping events.
Routed account keys are durable: existing contacts/conversations stay on the
account that created them, and a re-link reuses the same row (generation bump).

The resolver is the only path that reads an OA account's lifecycle state for
ingress/dispatch; credential decryption stays in the settings service.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import types as ct

logger = logging.getLogger(__name__)

# Advisory lock fencing link/unlink against in-flight dispatch (distinct from
# the Facebook Page lock so the two lifecycles never serialize each other).
ZALO_OA_ACCOUNT_AUTHORITY_LOCK = 7_423_811_611

# Zalo OA ids are numeric and bounded; the column is String(128).
ZALO_OA_ID_MAX_LENGTH = 64


class ZaloOaAccountError(RuntimeError):
    """Base class for OA account lifecycle failures."""


class ZaloOaAccountInvalidError(ZaloOaAccountError):
    """The supplied OA id is malformed or reserved (→ 422)."""


def default_oa_account_key() -> str:
    """The seeded single-OA account key (imported lazily to avoid a cycle)."""
    from app.services.integration_settings.providers.zalo import (
        ZALO_OA_DEFAULT_ACCOUNT_KEY,
    )

    return ZALO_OA_DEFAULT_ACCOUNT_KEY


async def acquire_zalo_oa_account_lock(db: AsyncSession, *, shared: bool) -> None:
    """Fence OA account lifecycle changes against in-flight provider dispatch."""
    lock = (
        func.pg_advisory_xact_lock_shared(ZALO_OA_ACCOUNT_AUTHORITY_LOCK)
        if shared
        else func.pg_advisory_xact_lock(ZALO_OA_ACCOUNT_AUTHORITY_LOCK)
    )
    await db.execute(select(lock))


def validate_oa_id(oa_id: str) -> str:
    """Return the normalized OA id or raise ``ZaloOaAccountInvalidError``."""
    cleaned = (oa_id or "").strip()
    if not cleaned or len(cleaned) > ZALO_OA_ID_MAX_LENGTH:
        raise ZaloOaAccountInvalidError("mã OA không hợp lệ")
    if not cleaned.isdigit():
        raise ZaloOaAccountInvalidError("mã OA phải là dãy số Zalo cấp cho OA")
    if cleaned == default_oa_account_key():
        raise ZaloOaAccountInvalidError("mã OA này được dành cho OA gốc")
    return cleaned


class ZaloOaAccountResolver:
    """Resolve ``zalo_oa`` channel accounts and route inbound events to one."""

    PROVIDER = ct.PROVIDER_ZALO_OA

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def support_oa_id(self) -> str:
        """The linked TingTing support OA's own id, or "" when unlinked.

        Read from the channel account's provider metadata (written by
        ``TingtingOaLinkService`` after Zalo's ``getoa`` confirmed it), so no
        admin ever types an OA id.
        """
        from app.services.tingting_oa import TingtingOaLinkService

        return await TingtingOaLinkService(self.db).verified_oa_id()

    async def account_key_for_payload(self, payload: dict) -> str:
        """Route one OA webhook body to its account key.

        Falls back to the default account when the body names no OA id, or
        names one that is not this deployment's support OA — never drops the
        event. The id comes from the parsed event (``ZaloOAWebhookEvent.oa_id``),
        which knows the role the OA holds in that event's shape: receipt events
        invert it, so reading the recipient there would match a user id.
        """
        from app.channels.types import TINGTING_OA_ACCOUNT_KEY
        from app.services.zalo_oa_events import parse_oa_webhook_event

        event = parse_oa_webhook_event(payload)
        oa_id = event.oa_id if event is not None else ""
        if oa_id:
            if await self.support_oa_id() == oa_id:
                return TINGTING_OA_ACCOUNT_KEY
            logger.info(
                "zalo oa event for an unlinked oa_id length=%d -> default account",
                len(oa_id),
            )
        return default_oa_account_key()


__all__ = [
    "ZALO_OA_ACCOUNT_AUTHORITY_LOCK",
    "ZaloOaAccountError",
    "ZaloOaAccountInvalidError",
    "ZaloOaAccountResolver",
    "acquire_zalo_oa_account_lock",
    "default_oa_account_key",
    "validate_oa_id",
]
