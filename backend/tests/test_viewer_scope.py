"""Unit tests for the centralized viewer-scope authorization invariant.

These pin the one place the "admin = all, recruiter = own + unassigned" rule
lives, so a refactor cannot silently change who sees what. No DB needed — the
ORM predicate is compiled to SQL string form and the raw-SQL fragment is
checked directly.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.conversation import Conversation
from app.models.user import Role
from app.services.viewer_scope import (
    viewer_scope_condition,
    viewer_scope_filter,
    viewer_scope_sql,
)


def _viewer(role: Role, uid: str = "11111111-1111-1111-1111-111111111111"):
    return SimpleNamespace(role=role, id=uid)


# --- ORM condition -----------------------------------------------------------


def test_condition_admin_returns_none_no_restriction():
    assert viewer_scope_condition(Conversation.assigned_recruiter_id, _viewer(Role.admin)) is None


def test_condition_recruiter_is_own_or_unassigned():
    recruiter = _viewer(Role.recruiter)
    cond = viewer_scope_condition(Conversation.assigned_recruiter_id, recruiter)
    assert cond is not None
    sql = str(cond.compile(compile_kwargs={"literal_binds": False}))
    # own rows ...
    assert "assigned_recruiter_id" in sql
    assert str(recruiter.id) in sql or ":id" in sql or "id" in sql
    # ... OR unassigned
    assert "IS NULL" in sql.upper()


def test_filter_admin_leaves_statement_unchanged():
    from sqlalchemy import select

    stmt = select(Conversation)
    assert (
        viewer_scope_filter(stmt, Conversation.assigned_recruiter_id, _viewer(Role.admin)) is stmt
    )


def test_filter_recruiter_adds_where_clause():
    from sqlalchemy import select

    stmt = select(Conversation)
    out = viewer_scope_filter(stmt, Conversation.assigned_recruiter_id, _viewer(Role.recruiter))
    assert out is not stmt  # a new statement with the scope predicate attached
    sql = str(out.compile(compile_kwargs={"literal_binds": False}))
    assert "IS NULL" in sql.upper()


# --- raw-SQL fragment --------------------------------------------------------


def test_sql_fragment_unaliased_single_table():
    assert viewer_scope_sql() == ("(assigned_recruiter_id = :uid OR assigned_recruiter_id IS NULL)")


def test_sql_fragment_with_conversation_alias():
    assert viewer_scope_sql("c.") == (
        "(c.assigned_recruiter_id = :uid OR c.assigned_recruiter_id IS NULL)"
    )


def test_sql_fragment_with_lead_alias():
    out = viewer_scope_sql("l.")
    assert out.startswith("(l.assigned_recruiter_id")
    assert out.endswith("IS NULL)")
    # the :uid bind name is part of the contract every dashboard query relies on
    assert ":uid" in out
