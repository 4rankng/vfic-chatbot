"""PostgreSQL coverage for provider-scoped conversation inbox queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.lead import Lead, LeadScore
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
    await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-semi-auto-unassigned",
        zalo_chat_id="searchable-semi-auto-unassigned",
        mode=ConversationMode.SEMI_AUTO,
        last_inbound_at=common["last_inbound_at"],
        last_outbound_at=common["last_outbound_at"],
    )
    await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-bot-mode-unassigned",
        zalo_chat_id="searchable-bot-mode-unassigned",
        mode=ConversationMode.BOT,
        last_inbound_at=common["last_inbound_at"],
        last_outbound_at=common["last_outbound_at"],
    )
    open_without_outbound = await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-open-no-outbound",
        zalo_chat_id="searchable-open-no-outbound",
        mode=ConversationMode.HUMAN,
        last_inbound_at=now - timedelta(minutes=5),
        last_outbound_at=None,
    )
    closed_failed_delivery = await make_conversation(
        integration_session,
        provider="zalo_bot",
        account_key="bot-account",
        external_id="searchable-closed-failed-delivery",
        zalo_chat_id="searchable-closed-failed-delivery",
        mode=ConversationMode.HUMAN,
        status=ConversationStatus.CLOSED,
        last_inbound_at=now - timedelta(minutes=5),
        last_outbound_at=None,
    )
    integration_session.add_all(
        [
            Message(
                conversation_id=open_without_outbound.id,
                sender=MessageSender.RECRUITER,
                body="Open failed delivery",
                delivery_status=DeliveryStatus.FAILED,
                created_at=now,
            ),
            Message(
                conversation_id=closed_failed_delivery.id,
                sender=MessageSender.RECRUITER,
                body="Closed failed delivery",
                delivery_status=DeliveryStatus.FAILED,
                created_at=now,
            ),
        ]
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
    assert {row.id for row in bot_rows} == {
        bot_unassigned.id,
        bot_owned.id,
        open_without_outbound.id,
    }
    assert bot_total == 3

    assert await service.needs_attention_count(
        viewer=recruiter, channel_provider="zalo_oa"
    ) == 2
    assert await service.needs_attention_count(viewer=recruiter) == 5

    from app.composition.reporting import run_conversation_attention_query

    async def attention_page(*, reason, channel_provider=None, page, per_page):
        return await run_conversation_attention_query(
            integration_session,
            viewer=recruiter,
            reason=reason,
            channel_provider=channel_provider,
            page=page,
            per_page=per_page,
        )

    first_page, total = await attention_page(
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=1,
        per_page=1,
    )
    second_page, second_total = await attention_page(
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=2,
        per_page=1,
    )
    beyond_page, beyond_total = await attention_page(
        reason="REPLY_OVERDUE",
        channel_provider="zalo_oa",
        page=3,
        per_page=1,
    )
    assert {first_page[0].id, second_page[0].id} == {oa_unassigned.id, oa_owned.id}
    assert total == second_total == beyond_total == 2
    assert beyond_page == []

    aggregate, aggregate_total = await attention_page(
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
    unread_rows, unread_total = await attention_page(
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
    counters = await dashboard_repo.attention_counters(str(recruiter.id))
    assert counters["needs_reply"] == 5
    assert counters["priority"] == 1
    immediate = await dashboard_repo.attention_rows(str(recruiter.id), "immediate", limit=20)
    immediate_ids = {row["conversation_id"] for row in immediate}
    assert open_without_outbound.id in immediate_ids
    assert closed_failed_delivery.id not in immediate_ids

    delivery_ids, delivery_total = await dashboard_repo.attention_reason_page(
        str(recruiter.id),
        reason="DELIVERY_REVIEW",
        channel_provider="zalo_bot",
        page=1,
        per_page=10,
    )
    assert delivery_ids == [open_without_outbound.id]
    assert delivery_total == 1

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


async def test_lead_reason_suppression_is_scoped_to_selected_provider(
    integration_session,
) -> None:
    """Activity on one adapter must not hide another adapter's lead action."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=4)
    contact = Contact(display_name="Shared adapter contact")
    integration_session.add(contact)
    await integration_session.flush()
    bot_identity = ContactChannelIdentity(
        contact_id=contact.id,
        provider="zalo_bot",
        account_key="shared-bot",
        external_id="shared-candidate",
    )
    oa_identity = ContactChannelIdentity(
        contact_id=contact.id,
        provider="zalo_oa",
        account_key="shared-oa",
        external_id="shared-candidate",
    )
    integration_session.add_all([bot_identity, oa_identity])
    await integration_session.flush()
    bot_conversation = Conversation(
        contact_id=contact.id,
        channel_identity_id=bot_identity.id,
        zalo_chat_id="shared-candidate",
        updated_at=old,
        last_inbound_at=now,
        last_outbound_at=old,
    )
    oa_conversation = Conversation(
        contact_id=contact.id,
        channel_identity_id=oa_identity.id,
        zalo_chat_id="oa:shared-candidate",
        zalo_channel="oa",
        updated_at=old,
        last_inbound_at=old,
        last_outbound_at=old,
    )
    integration_session.add_all([bot_conversation, oa_conversation])
    await integration_session.flush()

    lead = (
        await integration_session.scalars(select(Lead).where(Lead.contact_id == contact.id))
    ).one()
    lead.lead_score = LeadScore.hot
    lead.updated_at = old
    integration_session.add(
        Message(
            conversation_id=bot_conversation.id,
            sender=MessageSender.RECRUITER,
            body="Bot-channel recruiter reply",
            created_at=now,
        )
    )
    await integration_session.flush()

    repo = DashboardRepository(integration_session)

    priority_ids, priority_total = await repo.attention_reason_page(
        None,
        reason="PRIORITY_NO_ACTION",
        channel_provider="zalo_oa",
        page=1,
        per_page=10,
    )
    assert priority_ids == [oa_conversation.id]
    assert priority_total == 1
    _aggregate_priority_ids, aggregate_priority_total = await repo.attention_reason_page(
        None,
        reason="PRIORITY_NO_ACTION",
        channel_provider=None,
        page=1,
        per_page=10,
    )
    assert aggregate_priority_total == 0

    stalled_ids, stalled_total = await repo.attention_reason_page(
        None,
        reason="STALLED",
        channel_provider="zalo_oa",
        page=1,
        per_page=10,
    )
    assert stalled_ids == [oa_conversation.id]
    assert stalled_total == 1
    _aggregate_stalled_ids, aggregate_stalled_total = await repo.attention_reason_page(
        None,
        reason="STALLED",
        channel_provider=None,
        page=1,
        per_page=10,
    )
    assert aggregate_stalled_total == 0

    # Same-provider recruiter reply and activity suppress the selected OA rows.
    integration_session.add(
        Message(
            conversation_id=oa_conversation.id,
            sender=MessageSender.RECRUITER,
            body="OA-channel recruiter reply",
            created_at=now,
        )
    )
    oa_conversation.last_inbound_at = now
    await integration_session.flush()

    _priority_ids, priority_total = await repo.attention_reason_page(
        None,
        reason="PRIORITY_NO_ACTION",
        channel_provider="zalo_oa",
        page=1,
        per_page=10,
    )
    _stalled_ids, stalled_total = await repo.attention_reason_page(
        None,
        reason="STALLED",
        channel_provider="zalo_oa",
        page=1,
        per_page=10,
    )
    assert priority_total == 0
    assert stalled_total == 0
