"""Admin-only rule for the employee-support (TingTing) Zalo OA.

The support OA carries employee password resets, not recruitment: only admins
may read those threads, and none of them enters the recruiting pipeline. These
tests pin the predicate itself (compiled SQL), because the rule has to hold at
every read site that shares it — list, message page, counters, socket, dashboard
and the lead lists.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.user import Role
from app.services.conversation.repository import ConversationRepository
from app.services.tingting_oa import TINGTING_OA_ACCOUNT_KEY
from app.services.viewer_scope import (
    support_account_condition,
    support_account_sql,
    support_leads_sql,
    viewer_can_access_conversation,
    viewer_conversation_filter,
    viewer_lead_filter,
)


def _compiled(stmt) -> str:
    # Literal binds so the account key and provider are visible in the SQL the
    # assertions read (psycopg would otherwise see only bind placeholders).
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _viewer(role: Role) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), role=role)


def test_a_recruiter_never_reads_the_support_oa_threads():
    stmt = viewer_conversation_filter(select(Conversation), _viewer(Role.recruiter))
    sql = _compiled(stmt)

    assert "support_scope_identity" in sql
    assert TINGTING_OA_ACCOUNT_KEY in sql
    assert "assigned_recruiter_id" in sql
    assert "NOT (EXISTS" in sql


def test_an_admin_reads_everything():
    sql = _compiled(
        viewer_conversation_filter(select(Conversation), _viewer(Role.admin))
    )

    # No restriction at all: neither the recruiter rule nor the support exclusion.
    assert "support_scope_identity" not in sql
    assert "IS NULL" not in sql
    assert "WHERE" not in sql


def test_the_lead_list_also_excludes_support_contacts():
    recruiter_sql = _compiled(viewer_lead_filter(select(Lead), _viewer(Role.recruiter)))
    assert "support_lead_identity" in recruiter_sql
    admin_sql = _compiled(viewer_lead_filter(select(Lead), _viewer(Role.admin)))
    assert "support_lead_identity" not in admin_sql


def test_the_support_account_predicate_is_a_correlated_not_exists():
    sql = _compiled(select(Conversation.id).where(support_account_condition()))

    assert "NOT (EXISTS" in sql
    assert "contact_channel_identities" in sql
    assert f"'{TINGTING_OA_ACCOUNT_KEY}'" in sql


def test_the_raw_sql_twins_carry_the_alias():
    assert "support_scope_identity.id = c.channel_identity_id" in support_account_sql("c.")
    assert "support_lead_identity.contact_id = l.contact_id" in support_leads_sql("l.")
    assert "support_scope_identity.id = channel_identity_id" in support_account_sql()


async def test_the_socket_check_refuses_a_recruiter_on_a_support_thread():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    assert await viewer_can_access_conversation(db, uuid4(), _viewer(Role.recruiter)) is False
    sql = _compiled(db.scalar.await_args.args[0])
    assert "support_scope_identity" in sql


def test_the_conversations_filter_narrows_to_the_support_account():
    condition = ConversationRepository._channel_filter_condition("tingting_oa")
    sql = _compiled(select(Conversation.id).where(condition))

    assert "provider" in sql
    assert f"account_key = '{TINGTING_OA_ACCOUNT_KEY}'" in sql


def test_the_conversations_filter_still_matches_a_plain_provider():
    condition = ConversationRepository._channel_filter_condition("zalo_bot")
    sql = _compiled(select(Conversation.id).where(condition))

    assert "account_key" not in sql
    assert "zalo_bot" in sql


@pytest.mark.parametrize("provider", ["zalo_bot", "zalo_oa", "facebook_messenger", "tingting_oa"])
def test_every_badge_value_is_a_known_provider_or_the_support_account(provider: str):
    """The API Literal and the filter mapping must accept the same values."""
    from app.api.conversations import ChannelProvider

    condition = ConversationRepository._channel_filter_condition(provider)
    assert condition is not None
    assert provider in ChannelProvider.__args__  # type: ignore[attr-defined]
