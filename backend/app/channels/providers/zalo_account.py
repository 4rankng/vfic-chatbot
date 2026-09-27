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
from app.channels.accounts import ChannelAccountStatus
from app.models.channel_account import ChannelAccount
from app.services.audit_service import record_audit

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


class ZaloOaAccountNotFoundError(ZaloOaAccountError):
    """No ``zalo_oa`` channel account exists for the requested key (→ 404)."""


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

    async def _fetch(self, account_key: str) -> ChannelAccount | None:
        return await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == self.PROVIDER,
                ChannelAccount.account_key == account_key,
            )
        )

    async def resolve_active(self, account_key: str) -> ChannelAccount | None:
        """The ACTIVE row for one account key, or ``None``."""
        row = await self._fetch(account_key)
        if row is None or not row.is_active:
            return None
        return row

    async def active_accounts(self) -> list[ChannelAccount]:
        """Every ACTIVE ``zalo_oa`` account (the default OA is always one)."""
        rows = (
            await self.db.scalars(
                select(ChannelAccount)
                .where(
                    ChannelAccount.provider == self.PROVIDER,
                    ChannelAccount.status == ChannelAccountStatus.ACTIVE,
                )
                .order_by(ChannelAccount.account_key)
            )
        ).all()
        return list(rows)

    async def account_key_for_payload(self, payload: dict) -> str:
        """Route one OA webhook body to its account key.

        Falls back to the default account when the body carries no ``oa_id`` or
        names one that is not a linked, active OA — never drops the event.
        """
        from app.services.zalo_oa_events import oa_id_from_payload

        oa_id = oa_id_from_payload(payload)
        if oa_id:
            row = await self._fetch(oa_id)
            if row is not None and row.is_active:
                return row.account_key
            logger.info(
                "zalo oa event for unlinked oa_id length=%d -> default account",
                len(oa_id),
            )
        return default_oa_account_key()


class ZaloOaAccountLifecycle:
    """Admin-facing link/unlink for additional OA accounts.

    Linking writes the channel-account row and its namespaced credentials in one
    transaction and bumps the generation, so in-flight outbound work queued
    under the previous authority is fenced (the dispatcher compares generations).
    Unlinking marks the row INACTIVE and clears the stored credentials: history
    stays readable, but no token remains that could send as that OA.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_accounts(self) -> list[ChannelAccount]:
        rows = (
            await self.db.scalars(
                select(ChannelAccount)
                .where(ChannelAccount.provider == ct.PROVIDER_ZALO_OA)
                .order_by(ChannelAccount.status, ChannelAccount.account_key)
            )
        ).all()
        return list(rows)

    async def link(
        self,
        *,
        oa_id: str,
        label: str,
        credentials: dict[str, str | None],
        actor_id=None,
    ) -> ChannelAccount:
        """Create or reactivate one OA account, storing its own credentials."""
        from app.services.integration_settings import IntegrationSettingsService
        from app.services.integration_settings.providers.zalo import ZALO_OA_ACCESS_TOKEN

        account_key = validate_oa_id(oa_id)
        settings_service = IntegrationSettingsService(self.db)
        stored = {
            base: value
            for base, value in credentials.items()
            if value is not None and str(value).strip()
        }
        # The OA cannot answer without an access token; refuse the link instead
        # of registering an account that fails closed on every send.
        access_token = str(stored.get(ZALO_OA_ACCESS_TOKEN) or "").strip()
        if not access_token:
            raise ZaloOaAccountInvalidError("cần access token của OA")
        # Linking the *original* OA under its real OA id would re-key every
        # future event of that OA onto a new identity (splitting live
        # conversations from their history). The same access token identifies
        # the same OA, so refuse it and point at the existing config instead.
        default_cfg = await settings_service.resolve_zalo()
        if default_cfg.oa_access_token and default_cfg.oa_access_token == access_token:
            raise ZaloOaAccountInvalidError(
                "access token này thuộc OA gốc đang cấu hình — hãy dùng phần cấu hình OA hiện tại"
            )

        await acquire_zalo_oa_account_lock(self.db, shared=False)
        row = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_ZALO_OA,
                ChannelAccount.account_key == account_key,
            )
        )
        if row is None:
            row = ChannelAccount(
                provider=ct.PROVIDER_ZALO_OA,
                account_key=account_key,
                label=(label or "").strip() or f"Zalo OA {account_key}",
                status=ChannelAccountStatus.ACTIVE,
                generation=1,
            )
            self.db.add(row)
        else:
            row.label = (label or "").strip() or row.label
            if not row.is_active:
                row.generation = int(row.generation or 0) + 1
            row.status = ChannelAccountStatus.ACTIVE
        await self.db.flush()

        changed = await settings_service.write_oa_account_credentials(
            account_key, credentials, actor_id=actor_id
        )
        await record_audit(
            self.db,
            action="link_zalo_oa_account",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=account_key,
            payload={"changed_keys": changed, "label": row.label},
        )
        await self.db.commit()
        await self.db.refresh(row)
        await _bump_zalo_cache()
        return row

    async def unlink(self, account_key: str, *, actor_id=None) -> None:
        """Deactivate one OA account and destroy its stored credentials."""
        from app.services.integration_settings import IntegrationSettingsService

        row = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_ZALO_OA,
                ChannelAccount.account_key == account_key,
            )
        )
        if row is None:
            raise ZaloOaAccountNotFoundError("chưa liên kết OA này")
        if row.account_key == default_oa_account_key():
            raise ZaloOaAccountInvalidError("không thể gỡ OA gốc")

        await acquire_zalo_oa_account_lock(self.db, shared=False)
        row.status = ChannelAccountStatus.INACTIVE
        row.generation = int(row.generation or 0) + 1
        cleared = await IntegrationSettingsService(
            self.db
        ).clear_oa_account_credentials(account_key)
        await record_audit(
            self.db,
            action="unlink_zalo_oa_account",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=account_key,
            payload={"cleared_credentials": cleared},
        )
        await self.db.commit()
        await _bump_zalo_cache()


async def _bump_zalo_cache() -> None:
    """Invalidate the Zalo config cache (this process and every other one).

    The version bump is what a worker in another container sees; the local
    eviction covers this process immediately. A Redis failure must not undo a
    committed link, so it is logged and swallowed.
    """
    from app.core.cache import bump_cache_version
    from app.core.preamble_cache import NS_INTEGRATION_ZALO, evict_local_namespace

    evict_local_namespace(NS_INTEGRATION_ZALO)
    try:
        await bump_cache_version(NS_INTEGRATION_ZALO)
    except Exception:  # noqa: BLE001
        logger.warning("zalo cache version bump failed", exc_info=True)


__all__ = [
    "ZALO_OA_ACCOUNT_AUTHORITY_LOCK",
    "ZaloOaAccountError",
    "ZaloOaAccountInvalidError",
    "ZaloOaAccountLifecycle",
    "ZaloOaAccountNotFoundError",
    "ZaloOaAccountResolver",
    "acquire_zalo_oa_account_lock",
    "default_oa_account_key",
    "validate_oa_id",
]
