"""Facebook account resolver + Page lifecycle (Phase 4).

Implements the shared :class:`ChannelAccountResolver` port for the
``facebook_messenger`` provider and owns the recoverable Page-lifecycle state
machine: pending → active, reconnect (same Page reuses the account), Page
replacement (old account becomes inactive/distinct), and disconnect (inactive,
read-only history, never deleted).

The resolver is the ONLY path that decrypts a Page token for an active account.
Shared dispatch/ingress/graph services resolve authority through this port;
they never import the OAuth client or the integration-settings service.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import types as ct
from app.channels.ports import ChannelAccountResolver
from app.models.channel_account import ChannelAccount
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)


class FacebookAccountResolver(ChannelAccountResolver):
    """Resolve active/inactive ``facebook_messenger`` channel accounts.

    Backed by the ``channel_accounts`` table (Alembic 0047). The partial unique
    index ``uq_channel_accounts_one_active_facebook_messenger`` enforces at most
    one active Page in V1 at the DB level.
    """

    PROVIDER = ct.PROVIDER_FACEBOOK_MESSENGER

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _fetch(
        self, *, provider: str, account_key: str, only_active: bool
    ) -> ChannelAccount | None:
        stmt = select(ChannelAccount).where(
            ChannelAccount.provider == provider,
            ChannelAccount.account_key == account_key,
        )
        if only_active:
            stmt = stmt.where(ChannelAccount.status == ChannelAccountStatus.ACTIVE)
        return await self.db.scalar(stmt)

    async def resolve_active(
        self, *, provider: str, account_key: str
    ) -> ct.ChannelAccountRef | None:
        row = await self._fetch(provider=provider, account_key=account_key, only_active=True)
        return _to_ref(row)

    async def resolve_any(self, *, provider: str, account_key: str) -> ct.ChannelAccountRef | None:
        row = await self._fetch(provider=provider, account_key=account_key, only_active=False)
        return _to_ref(row)

    async def active_facebook_page(self) -> ct.ChannelAccountRef | None:
        """The one active facebook_messenger Page (V1: at most one)."""
        row = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == self.PROVIDER,
                ChannelAccount.status == ChannelAccountStatus.ACTIVE,
            )
        )
        return _to_ref(row)

    async def list_facebook_accounts(self) -> list[ct.ChannelAccountRef]:
        """All facebook_messenger accounts (active + archived)."""
        rows = (
            await self.db.scalars(
                select(ChannelAccount)
                .where(ChannelAccount.provider == self.PROVIDER)
                .order_by(ChannelAccount.status, ChannelAccount.updated_at.desc())
            )
        ).all()
        return [_to_ref(r) for r in rows if r is not None]


# Import here to avoid a circular import at module top.
from app.channels.accounts import ChannelAccountStatus  # noqa: E402


def _to_ref(row: ChannelAccount | None) -> ct.ChannelAccountRef | None:
    if row is None:
        return None
    return ct.ChannelAccountRef(
        id=str(row.id),
        provider=row.provider,
        account_key=row.account_key,
        label=row.label,
        status=row.status,
        generation=int(row.generation or 0),
    )


class FacebookPageLifecycle:
    """Recoverable Page-lifecycle state machine (not a Postgres+Meta transaction).

    Each transition is committed atomically with an audit row. A crash mid-
    flow leaves a PENDING operation that the reconciler (or a re-issue of the
    same admin action) resumes or compensates. Failures retain the prior
    working generation; a bad reconnect never breaks the active connection.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def activate_or_reactivate(
        self,
        *,
        page_id: str,
        page_name: str,
        page_access_token: str,
        admin_id,
    ) -> ChannelAccount:
        """Persist authority + activate the Page, archiving any prior active Page.

        Same-Page reactivation reuses the existing row and advances its
        generation (token rotation). A different Page creates a new row and
        marks the prior active Page INACTIVE (distinct history scope).

        Concurrency: two admins activating different Pages race on the partial
        unique index ``uq_channel_accounts_one_active_facebook_messenger``. The
        loser's commit raises IntegrityError; we roll back and retry once. The
        retry stages any now-active winner's deactivation in the same atomic
        account/token/audit transaction. The index is the final authority.
        """
        from sqlalchemy.exc import IntegrityError

        for attempt in (1, 2):
            try:
                return await self._activate_once(
                    page_id=page_id,
                    page_name=page_name,
                    page_access_token=page_access_token,
                    admin_id=admin_id,
                )
            except IntegrityError:
                if attempt == 2:
                    raise  # second collision → surface; the index is genuinely contested
                await self.db.rollback()
                # The retry observes the committed winner and changes it only
                # inside _activate_once's account+token+audit transaction.

    async def _activate_once(
        self,
        *,
        page_id: str,
        page_name: str,
        page_access_token: str,
        admin_id,
    ) -> ChannelAccount:
        from app.services.integration_settings import IntegrationSettingsService

        # 1. Resolve existing account for this Page id (reactivation) or None.
        existing = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
                ChannelAccount.account_key == page_id,
            )
        )
        # 2. Archive any OTHER currently-active Page (V1: at most one active).
        current_active = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
                ChannelAccount.status == ChannelAccountStatus.ACTIVE,
                ChannelAccount.account_key != page_id,
            )
        )
        new_generation = 1
        if current_active is not None:
            current_active.status = ChannelAccountStatus.INACTIVE
            current_active.updated_at = datetime.now(timezone.utc)
            new_generation = max(new_generation, int(current_active.generation or 0) + 1)

        # 3. Upsert the target account: reactivate existing or create new.
        if existing is not None:
            existing.status = ChannelAccountStatus.ACTIVE
            existing.label = page_name or existing.label
            existing.generation = max(int(existing.generation or 0) + 1, new_generation)
            existing.updated_at = datetime.now(timezone.utc)
            account = existing
        else:
            account = ChannelAccount(
                provider=ct.PROVIDER_FACEBOOK_MESSENGER,
                account_key=page_id,
                label=page_name or page_id,
                status=ChannelAccountStatus.ACTIVE,
                generation=new_generation,
            )
            self.db.add(account)

        await self.db.flush()
        # 4. Stage the encrypted Page token (context-bound to the page_id).
        settings_service = IntegrationSettingsService(self.db)
        await settings_service.stage_facebook_page_token_upsert(
            page_id, page_access_token, updated_by=admin_id
        )

        await record_audit(
            self.db,
            action="facebook_page_activated",
            actor_id=admin_id,
            target_type="channel_account",
            target_id=str(account.id),
            payload={
                "page_id_suffix": page_id[-4:] if page_id else "",
                "generation": int(account.generation or 0),
                "reactivated": existing is not None,
            },
        )
        await self.db.commit()
        await settings_service.invalidate_facebook_cache(best_effort=True)
        return account

    async def disconnect(self, *, page_id: str, admin_id) -> ChannelAccount | None:
        """Mark a Page inactive; never delete history. Invalidates caches."""
        from app.services.integration_settings import IntegrationSettingsService

        account = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
                ChannelAccount.account_key == page_id,
            )
        )
        if account is None:
            return None
        account.status = ChannelAccountStatus.INACTIVE
        account.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        # Stage token removal so account state + audit commit atomically.
        settings_service = IntegrationSettingsService(self.db)
        await settings_service.stage_facebook_page_token_delete(page_id)
        await record_audit(
            self.db,
            action="facebook_page_disconnected",
            actor_id=admin_id,
            target_type="channel_account",
            target_id=str(account.id),
            payload={"page_id_suffix": page_id[-4:] if page_id else ""},
        )
        await self.db.commit()
        await settings_service.invalidate_facebook_cache(best_effort=True)
        return account


__all__ = ["FacebookAccountResolver", "FacebookPageLifecycle"]
