"""The viewer-scope authorization invariant, in one place.

The rule "admins see everything; recruiters see rows assigned to them OR
unassigned" was duplicated across 14+ call sites in two syntaxes (SQLAlchemy
``or_(...)`` and raw SQL ``text()``) and had already drifted once. Centralize it
here so a future rule change edits these helpers, not a dozen scattered
predicates.

* :func:`viewer_scope_filter` / :func:`viewer_scope_condition` — ORM form
  (admin = no predicate; recruiter = own-or-unassigned). Use ``filter`` to apply
  to a ``Select`` directly, or ``condition`` when building a conditions list.
* :func:`viewer_scope_sql` — the equivalent raw-SQL fragment bound to ``:uid``.
  The caller still owns the admin/``None`` branch and the ``AND``/``WHERE``
  glue (those are tied to the surrounding query text); this owns the invariant.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import ColumnElement, Select, and_, exists, or_, select

from app.models.conversation import Conversation
from app.models.contact import ContactChannelIdentity
from app.models.lead import Lead
from app.models.user import Role, User


class ViewerIdentity(Protocol):
    """The identity fields required by viewer-scoped reads."""

    id: uuid.UUID
    role: Role


def viewer_scope_condition(
    column: ColumnElement, viewer: User | ViewerIdentity
) -> ColumnElement[bool] | None:
    """Return the ORM viewer-scope predicate, or ``None`` for admins.

    ``None`` means "no restriction" — callers should skip ``.where()`` entirely
    so admins get the unfiltered statement (this matches the prior inlined
    ``if viewer.role != Role.admin`` guard at every site).
    """
    if viewer.role == Role.admin:
        return None
    return or_(column == viewer.id, column.is_(None))


def viewer_scope_filter(
    stmt: Select, column: ColumnElement, viewer: User | ViewerIdentity
) -> Select:
    """Apply :func:`viewer_scope_condition` to a ``Select`` statement."""
    condition = viewer_scope_condition(column, viewer)
    return stmt.where(condition) if condition is not None else stmt


def support_account_condition() -> ColumnElement[bool]:
    """Predicate: the conversation does NOT belong to the employee-support OA.

    The TingTing support OA carries employee password resets, not recruitment:
    only admins may read those threads (operator requirement), so every
    conversation read for a non-admin excludes the account. One correlated
    ``NOT EXISTS`` on the canonical identity — no join, so it composes with any
    conversation query, including the raw-SQL dashboard ones.
    """
    from app.channels import types as ct
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    identity = ContactChannelIdentity.__table__.alias("support_scope_identity")
    return ~exists(
        select(1).where(
            and_(
                identity.c.id == Conversation.channel_identity_id,
                identity.c.provider == ct.PROVIDER_ZALO_OA,
                identity.c.account_key == TINGTING_OA_ACCOUNT_KEY,
            )
        )
    )


def support_account_sql(alias: str = "") -> str:
    """Raw-SQL twin of :func:`support_account_condition`.

    ``alias`` is the conversations table prefix including the dot (``"c."``), or
    ``""`` for an un-aliased single-table query.
    """
    from app.channels import types as ct
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    return (
        "NOT EXISTS (SELECT 1 FROM contact_channel_identities support_scope_identity "
        f"WHERE support_scope_identity.id = {alias}channel_identity_id "
        f"AND support_scope_identity.provider = '{ct.PROVIDER_ZALO_OA}' "
        f"AND support_scope_identity.account_key = '{TINGTING_OA_ACCOUNT_KEY}')"
    )


def support_leads_condition() -> ColumnElement[bool]:
    """Predicate: the lead does NOT belong to an employee-support OA contact.

    The conversation-lead trigger (alembic 0025) stubs a Lead for every
    conversation, including the support OA's; those are staff, not candidates, so
    a recruiter must not see them in any lead list or pipeline aggregate."""
    from app.channels import types as ct
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    identity = ContactChannelIdentity.__table__.alias("support_lead_identity")
    return ~exists(
        select(1).where(
            and_(
                identity.c.contact_id == Lead.contact_id,
                identity.c.provider == ct.PROVIDER_ZALO_OA,
                identity.c.account_key == TINGTING_OA_ACCOUNT_KEY,
            )
        )
    )


def support_leads_sql(alias: str = "") -> str:
    """Raw-SQL twin of :func:`support_leads_condition` (``alias`` = ``"l."`` or "")."""
    from app.channels import types as ct
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    return (
        "NOT EXISTS (SELECT 1 FROM contact_channel_identities support_lead_identity "
        f"WHERE support_lead_identity.contact_id = {alias}contact_id "
        f"AND support_lead_identity.provider = '{ct.PROVIDER_ZALO_OA}' "
        f"AND support_lead_identity.account_key = '{TINGTING_OA_ACCOUNT_KEY}')"
    )


def viewer_lead_filter(stmt: Select, viewer: User | ViewerIdentity) -> Select:
    """Viewer scope for a lead read, plus the admin-only support contacts."""
    scoped = viewer_scope_filter(stmt, Lead.assigned_recruiter_id, viewer)
    if viewer.role == Role.admin:
        return scoped
    return scoped.where(support_leads_condition())


def viewer_conversation_filter(stmt: Select, viewer: User | ViewerIdentity) -> Select:
    """Viewer scope for a conversation read, plus the admin-only support OA.

    Every conversation read goes through this: the assigned-recruiter invariant
    plus the employee-support account exclusion, which is what makes those
    threads invisible to recruiters on the list, the message page, the counters
    and the realtime socket alike.
    """
    scoped = viewer_scope_filter(stmt, Conversation.assigned_recruiter_id, viewer)
    if viewer.role == Role.admin:
        return scoped
    return scoped.where(support_account_condition())


async def viewer_can_access_conversation(
    db, conversation_id: uuid.UUID, viewer: User | ViewerIdentity
) -> bool:
    """Return whether ``viewer`` may subscribe to one conversation."""
    stmt = viewer_conversation_filter(
        select(Conversation.id).where(Conversation.id == conversation_id),
        viewer,
    )
    return (await db.scalar(stmt)) is not None


async def viewer_can_access_lead(db, lead_id: int, viewer: User | ViewerIdentity) -> bool:
    """Return whether ``viewer`` may subscribe to one lead."""
    stmt = viewer_lead_filter(select(Lead.id).where(Lead.id == lead_id), viewer)
    return (await db.scalar(stmt)) is not None


def viewer_scope_sql(alias: str = "") -> str:
    """The raw-SQL viewer-scope fragment, bound to the ``:uid`` parameter.

    ``alias`` is the table prefix including the trailing dot (``"c."``, ``"l."``)
    or ``""`` for an un-aliased single-table query. Always wrapped in
    parentheses so it composes safely after ``AND`` / ``WHERE``.
    """
    col = f"{alias}assigned_recruiter_id"
    return f"({col} = :uid OR {col} IS NULL)"


__all__ = [
    "ViewerIdentity",
    "support_account_condition",
    "support_account_sql",
    "support_leads_condition",
    "support_leads_sql",
    "viewer_lead_filter",
    "viewer_can_access_conversation",
    "viewer_can_access_lead",
    "viewer_conversation_filter",
    "viewer_scope_condition",
    "viewer_scope_filter",
    "viewer_scope_sql",
]
