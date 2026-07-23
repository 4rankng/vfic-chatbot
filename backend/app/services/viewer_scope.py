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

from sqlalchemy import ColumnElement, Select, or_, select

from app.models.conversation import Conversation
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


async def viewer_can_access_conversation(
    db, conversation_id: uuid.UUID, viewer: User | ViewerIdentity
) -> bool:
    """Return whether ``viewer`` may subscribe to one conversation."""
    stmt = viewer_scope_filter(
        select(Conversation.id).where(Conversation.id == conversation_id),
        Conversation.assigned_recruiter_id,
        viewer,
    )
    return (await db.scalar(stmt)) is not None


async def viewer_can_access_lead(db, lead_id: int, viewer: User | ViewerIdentity) -> bool:
    """Return whether ``viewer`` may subscribe to one lead."""
    stmt = viewer_scope_filter(
        select(Lead.id).where(Lead.id == lead_id),
        Lead.assigned_recruiter_id,
        viewer,
    )
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
    "viewer_can_access_conversation",
    "viewer_can_access_lead",
    "viewer_scope_condition",
    "viewer_scope_filter",
    "viewer_scope_sql",
]
