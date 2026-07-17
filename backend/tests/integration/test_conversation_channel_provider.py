"""PostgreSQL coverage for provider-scoped conversation inbox queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import ConversationMode
from app.models.user import Role, User
from app.services.conversation import ConversationService
from app.services.dashboard.repository import DashboardRepository
from tests.integration._conv_factory import make_conversation

pytestmark = pytest.mark.integration


async def test_provider_scope_composes_with_search_attention_reason_and_viewer(
    integration_session,
) -> None:
    recruiter = User(
        email="provider-recruiter@test.local",
        password_hash="not-used",
        role=Role.recruiter,
    )
    other = User(
        email="provider-other@test.local",
        password_hash="not-used",
        role=Role.recruiter,
    )
    integration_session.add_all([recruiter, other])
    await integration_session.flush()

    now = datetime.now(timezone.utc)
    common = {
        "mode": ConversationMode.HUMAN,
        "last_inbound_at": now - timedelta(hours=2),
        "last_outbound_at": now - timedelta(hours=3),
    }
    bot_unassigned = await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-bot-unassigned",
        zalo_chat_id="searchable-bot-unassigned",
        unread_count=1,
        **common,
    )
    bot_owned = await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-bot-owned",
        zalo_chat_id="searchable-bot-owned",
        assigned_recruiter_id=recruiter.id,
        **common,
    )
    await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-bot-other",
        zalo_chat_id="searchable-bot-other",
        assigned_recruiter_id=other.id,
        **common,
    )
    oa_unassigned = await make_conversation(
        integration_session,
        provider="zalo_oa",
        account_key="oa-account",
        external_id="searchable-oa-unassigned",
        zalo_chat_id="oa:searchable-oa-unassigned",
        zalo_channel="oa",
        **common,
    )
    oa_owned = await make_conversation(
        integration_session,
        provider="zalo_oa",
        account_key="oa-account",
        external_id="searchable-oa-owned",
        zalo_chat_id="oa:searchable-oa-owned",
        zalo_channel="oa",
        assigned_recruiter_id=recruiter.id,
        **common,
    )
    await integration_session.flush()

    service = ConversationService(integration_session)
    bot_rows, bot_total = await service.list(
        viewer=recruiter,
        channel_provider="zalo_bot",
        q="searchable",
        needs_attention=True,
        per_page=10,
    )
    assert {row.id for row in bot_rows} == {bot_unassigned.id, bot_owned.id}
    assert bot_total == 2

    assert await service.needs_attention_count(
        viewer=recruiter, channel_provider="zalo_oa"
    ) == 2
    assert await service.needs_attention_count(viewer=recruiter) == 4

    first_page, total = await service.list_by_attention_reason(
        viewer=recruiter,
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=1,
        per_page=1,
    )
    second_page, second_total = await service.list_by_attention_reason(
        viewer=recruiter,
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=2,
        per_page=1,
    )
    beyond_page, beyond_total = await service.list_by_attention_reason(
        viewer=recruiter,
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=3,
        per_page=1,
    )
    assert {first_page[0].id, second_page[0].id} == {oa_unassigned.id, oa_owned.id}
    assert total == second_total == beyond_total == 2
    assert beyond_page == []

    aggregate, aggregate_total = await service.list_by_attention_reason(
        viewer=recruiter,
        reason="REPLY_OVERDUE",
        page=1,
        per_page=10,
    )
    assert {row.id for row in aggregate} == {
        bot_unassigned.id,
        bot_owned.id,
        oa_unassigned.id,
        oa_owned.id,
    }
    assert aggregate_total == 4

    # Reason continuations are independent by contract: this row qualifies for
    # both higher-precedence REPLY_OVERDUE and lower-precedence UNREAD.
    unread_rows, unread_total = await service.list_by_attention_reason(
        viewer=recruiter,
        reason="UNREAD",
        channel_provider="zalo_bot",
        page=1,
        per_page=10,
    )
    assert [row.id for row in unread_rows] == [bot_unassigned.id]
    assert unread_total == 1

    # Exercise every dedicated reason branch against PostgreSQL so provider
    # composition, enum literals, joins, and nullable totals stay executable.
    dashboard_repo = DashboardRepository(integration_session)
    for reason in (
        "DELIVERY_REVIEW",
        "HUMAN_ESCALATION",
        "REPLY_OVERDUE",
        "FOLLOWUP_OVERDUE",
        "WAITING_REPLY",
        "PRIORITY_NO_ACTION",
        "FOLLOWUP_TODAY",
        "UNREAD",
        "STALLED",
    ):
        _ids, reason_total = await dashboard_repo.attention_reason_page(
            str(recruiter.id),
            reason=reason,
            channel_provider="zalo_bot",
            page=1,
            per_page=2,
        )
        assert reason_total >= 0
