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
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import types as ct
from app.channels.ports import ChannelAccountResolver
from app.models.channel_account import ChannelAccount, ChannelAccountProject
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)


class FacebookPageUnassignedError(RuntimeError):
    """Activation gate: a Page needs >=1 mapping to a currently-ACTIVE Project.

    Multi-Page rollout, decision D1: without the gate an admin could activate a
    Page whose bot answers with an empty Project catalog on every turn. The
    count is of ACTIVE-project mappings (a mapping to an INACTIVE Project does
    not satisfy the gate), evaluated after the assignment is applied.
    """


FACEBOOK_PAGE_AUTHORITY_LOCK = 7_423_811_610


async def acquire_facebook_page_authority_lock(
    db: AsyncSession, *, shared: bool
) -> None:
    """Fence Page lifecycle changes against in-flight provider dispatch."""

    lock = (
        func.pg_advisory_xact_lock_shared(FACEBOOK_PAGE_AUTHORITY_LOCK)
        if shared
        else func.pg_advisory_xact_lock(FACEBOOK_PAGE_AUTHORITY_LOCK)
    )
    await db.execute(select(lock))


class FacebookAccountResolver(ChannelAccountResolver):
    """Resolve active/inactive ``facebook_messenger`` channel accounts.

    Backed by the ``channel_accounts`` table (Alembic 0047). Since Alembic
    0054 the partial unique index
    ``uq_channel_accounts_one_active_per_account`` enforces at most one ACTIVE
    row per (provider, account_key): a Page cannot be active twice, while many
    different Pages may each be active (multi-Page rollout).
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
        bot_paused=bool(getattr(row, "bot_paused", False)),
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
        project_ids: Sequence[str] | None = None,
    ) -> ChannelAccount:
        """Persist authority + activate the Page (multi-Page: no archive step).

        Same-Page reactivation reuses the existing row and advances its
        generation (token rotation). A different Page creates a new row and
        leaves every other active Page untouched — several Pages may be ACTIVE
        simultaneously (Alembic 0054 relaxed the V1 single-Page index to
        per-(provider, account_key) uniqueness).

        ``project_ids`` (optional, replace-all): the Page's Project assignment,
        applied atomically with activation. ``None`` keeps the existing
        assignment (reactivating a previously-connected Page resumes it).
        Decision D1 gates activation on >=1 mapping to a currently-ACTIVE
        Project after any assignment is applied; otherwise raises
        :class:`FacebookPageUnassignedError` and nothing commits.

        Concurrency: two admins activating the SAME Page race on the partial
        unique index ``uq_channel_accounts_one_active_per_account``. The
        loser's commit raises IntegrityError; we roll back and retry once. The
        retry re-reads the committed winner inside _activate_once's atomic
        account/mapping/token/audit transaction. The index is the final
        authority.
        """
        from sqlalchemy.exc import IntegrityError

        for attempt in (1, 2):
            try:
                return await self._activate_once(
                    page_id=page_id,
                    page_name=page_name,
                    page_access_token=page_access_token,
                    admin_id=admin_id,
                    project_ids=project_ids,
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
        project_ids: Sequence[str] | None = None,
    ) -> ChannelAccount:
        from app.services.integration_settings import IntegrationSettingsService

        await acquire_facebook_page_authority_lock(self.db, shared=False)
        # 1. Resolve existing account for this Page id (reactivation) or None.
        existing = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
                ChannelAccount.account_key == page_id,
            )
        )
        # 2. (Multi-Page: the V1 "archive any OTHER currently-active Page"
        #     step is REMOVED — other active Pages are never touched.)
        new_generation = 1

        # 3. Upsert the target account: reactivate existing or create new.
        if existing is not None:
            existing.status = ChannelAccountStatus.ACTIVE
            existing.label = page_name or existing.label
            existing.generation = int(existing.generation or 0) + 1
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

        # 4. Apply the optional replace-all Project assignment atomically with
        #    activation. Runs BEFORE the D1 gate and the commit, so a gate
        #    failure leaves neither the account change nor any mapping.
        if project_ids is not None:
            await self.db.execute(
                delete(ChannelAccountProject).where(
                    ChannelAccountProject.channel_account_id == account.id
                )
            )
            for pid in dict.fromkeys(project_ids):  # dedupe, keep order
                self.db.add(
                    ChannelAccountProject(
                        channel_account_id=account.id,
                        project_id=uuid.UUID(str(pid)),
                    )
                )
            await self.db.flush()

        # 5. D1 gate: >=1 mapping to a currently-ACTIVE Project after any
        #    (re)assignment. Fail-closed: raise BEFORE the commit so the whole
        #    transaction (account + mappings + token + audit) aborts.
        from app.models.company import Project as ProjectModel

        mapped_active = await self.db.scalar(
            select(func.count())
            .select_from(ChannelAccountProject)
            .join(ProjectModel, ProjectModel.id == ChannelAccountProject.project_id)
            .where(
                ChannelAccountProject.channel_account_id == account.id,
                ProjectModel.is_active.is_(True),
            )
        )
        if not mapped_active:
            raise FacebookPageUnassignedError(
                "facebook page activation requires at least one assigned active project"
            )

        # 6. Stage the encrypted Page token (context-bound to the page_id).
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
                "projects_replaced": project_ids is not None,
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
        await acquire_facebook_page_authority_lock(self.db, shared=False)
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


class FacebookPageNotFoundError(RuntimeError):
    """No facebook_messenger ChannelAccount exists for a given Page id.

    Domain-level (transport-free) so the API layer maps it to 404 without the
    service raising HTTP types.
    """


class FacebookPageAssignmentInvalidError(ValueError):
    """Assignment payload references malformed or unknown Project ids (→ 422)."""


class FacebookPageAssignmentView(NamedTuple):
    """Service-layer view of one Page↔Project assignment row.

    The API layer maps views onto ``FacebookPageProjectAssignmentOut`` without
    importing the ORM models itself.
    """

    project_id: str
    project_slug: str
    project_name: str
    project_active: bool


class FacebookPageAssignments:
    """Admin CRUD over the Page↔Project mapping (``channel_account_projects``).

    Each mutation commits atomically with an audit row, mirroring
    :class:`FacebookPageLifecycle`. The zero-ACTIVE-project gate (409) applies
    ONLY at activation (:class:`FacebookPageUnassignedError`); removing the
    last assignment of an ACTIVE Page is allowed here — the runtime catalog
    empties until an assignment returns, the same defense-in-depth
    empty-catalog behavior as an unmapped Page. Disconnect keeps assignment
    rows (decision D6); removal happens only through this surface.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def load_page(self, page_id: str) -> ChannelAccount:
        """Resolve a facebook_messenger ChannelAccount by Page id, or raise."""
        account = await self.db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
                ChannelAccount.account_key == page_id,
            )
        )
        if account is None:
            raise FacebookPageNotFoundError(
                "facebook page not found for assignment operations"
            )
        return account

    async def assignments(self, account_id) -> list[FacebookPageAssignmentView]:
        """Current Page↔Project assignment rows (stable created_at order)."""
        from app.models.company import Project

        rows = (
            await self.db.execute(
                select(ChannelAccountProject, Project)
                .join(Project, Project.id == ChannelAccountProject.project_id)
                .where(ChannelAccountProject.channel_account_id == account_id)
                .order_by(ChannelAccountProject.created_at.asc(), Project.name)
            )
        ).all()
        return [
            FacebookPageAssignmentView(
                project_id=str(project.id),
                project_slug=project.slug,
                project_name=project.name,
                project_active=bool(project.is_active),
            )
            for _mapping, project in rows
        ]

    async def validate_project_ids(
        self, project_ids: list[str]
    ) -> list[uuid.UUID]:
        """Dedupe + verify every entry is an existing Project id (→ 422)."""
        from app.models.company import Project

        try:
            wanted = [uuid.UUID(str(pid)) for pid in project_ids]
        except (ValueError, TypeError, AttributeError):
            raise FacebookPageAssignmentInvalidError(
                "Danh sách dự án không hợp lệ."
            ) from None
        wanted = list(dict.fromkeys(wanted))
        if wanted:
            found = set(
                await self.db.scalars(select(Project.id).where(Project.id.in_(wanted)))
            )
            if len(found) != len(wanted):
                raise FacebookPageAssignmentInvalidError(
                    "Một hoặc nhiều dự án không tồn tại."
                )
        return wanted

    async def replace(
        self, *, page_id: str, project_ids: list[str], actor_id
    ) -> tuple[ChannelAccount, list[FacebookPageAssignmentView]]:
        """Replace-all save from the multi-select editor (atomic delete+insert)."""
        account = await self.load_page(page_id)
        validated = await self.validate_project_ids(project_ids)
        await self.db.execute(
            delete(ChannelAccountProject).where(
                ChannelAccountProject.channel_account_id == account.id
            )
        )
        for pid in validated:
            self.db.add(ChannelAccountProject(channel_account_id=account.id, project_id=pid))
        await record_audit(
            self.db,
            action="facebook_page_projects_replaced",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=str(account.id),
            payload={
                "page_id_suffix": page_id[-4:] if page_id else "",
                "project_count": len(validated),
            },
        )
        await self.db.commit()
        return account, await self.assignments(account.id)

    async def add(
        self, *, page_id: str, project_id: str, actor_id
    ) -> tuple[ChannelAccount, list[FacebookPageAssignmentView], bool]:
        """Add one Project assignment. Idempotent when already assigned."""
        account = await self.load_page(page_id)
        (pid,) = await self.validate_project_ids([project_id])
        existing = await self.db.scalar(
            select(ChannelAccountProject).where(
                ChannelAccountProject.channel_account_id == account.id,
                ChannelAccountProject.project_id == pid,
            )
        )
        if existing is None:
            self.db.add(ChannelAccountProject(channel_account_id=account.id, project_id=pid))
            await record_audit(
                self.db,
                action="facebook_page_project_added",
                actor_id=actor_id,
                target_type="channel_account",
                target_id=str(account.id),
                payload={
                    "page_id_suffix": page_id[-4:] if page_id else "",
                    "project_id": str(pid),
                },
            )
            await self.db.commit()
        return account, await self.assignments(account.id), existing is None

    async def remove(
        self, *, page_id: str, project_id: str, actor_id
    ) -> list[FacebookPageAssignmentView] | None:
        """Remove one Project assignment; None when the assignment does not exist."""
        account = await self.load_page(page_id)
        try:
            pid = uuid.UUID(str(project_id))
        except (ValueError, TypeError, AttributeError):
            pid = None  # a malformed id can only be an unknown assignment → None
        mapping = (
            await self.db.scalar(
                select(ChannelAccountProject).where(
                    ChannelAccountProject.channel_account_id == account.id,
                    ChannelAccountProject.project_id == pid,
                )
            )
            if pid is not None
            else None
        )
        if mapping is None:
            return None
        await self.db.delete(mapping)
        await record_audit(
            self.db,
            action="facebook_page_project_removed",
            actor_id=actor_id,
            target_type="channel_account",
            target_id=str(account.id),
            payload={
                "page_id_suffix": page_id[-4:] if page_id else "",
                "project_id_suffix": str(project_id)[-4:],
            },
        )
        await self.db.commit()
        return await self.assignments(account.id)


__all__ = [
    "FACEBOOK_PAGE_AUTHORITY_LOCK",
    "FacebookAccountResolver",
    "FacebookPageAssignments",
    "FacebookPageAssignmentInvalidError",
    "FacebookPageAssignmentView",
    "FacebookPageLifecycle",
    "FacebookPageNotFoundError",
    "FacebookPageUnassignedError",
    "acquire_facebook_page_authority_lock",
]
