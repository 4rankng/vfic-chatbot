"""PostgreSQL coverage for the ChatOps follow-up calendar and version guard.

``ChatopsService.apply_action("schedule_followup")`` is the recruiter's in-chat
quick action: one call creates the ``FollowUpTask`` and stamps
``lead.next_action_at``. Two of its invariants are only provable against a real
database, because both cross a boundary the mocked unit tests stub out — the
``timestamptz`` round-trip and the real ``UPDATE ... WHERE version = N``.

* The due time is 09:00 on the *Vietnam* business calendar — the same calendar
  the dashboard's FOLLOWUP_TODAY counter matches on. A UTC-anchored 09:00 is
  16:00 ICT, so the task only surfaces after the recruiter's morning.
* The lead write carries the recruiter's version as its precondition, so a lead
  another recruiter already advanced is rejected (409) rather than silently
  clobbered — and leaves no follow-up behind.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text

from app.models.lead import FollowUpTask, FollowupStatus, Lead
from app.models.user import User
from app.services.dashboard.repository import DashboardRepository
from app.services.lead import LeadService
from app.services.lead.events import LeadEventBus
from app.services.lead.repository import LeadRepository
from app.shared.domain.errors import ConflictError
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration

_VN = ZoneInfo("Asia/Ho_Chi_Minh")


async def _recruiter(db) -> User:
    user = User(
        email=f"chatops-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        full_name="ChatOps Recruiter",
    )
    db.add(user)
    await db.flush()
    return user


async def _chatops_lead(db) -> Lead:
    """The lead behind a recruiter's in-chat panel — a real one, keyed by the
    conversation the chat arrived on (``leads.zalo_id`` is conversation-keyed)."""
    chat_id = f"chatops-{uuid.uuid4().hex}"
    await make_zalo_conversation(db, zalo_chat_id=chat_id)
    await db.flush()
    lead = await db.scalar(select(Lead).where(Lead.zalo_id == chat_id))
    assert lead is not None, "the conversation trigger supplies the lead"
    return lead


async def _is_followup_today(db, *, as_of: datetime) -> bool:
    """Does the dashboard's FOLLOWUP_TODAY predicate match a row at ``as_of``?

    Built from ``DashboardRepository._vn_today_predicate`` — the very string
    ``attention_counters`` feeds its ``due_today`` counter — with the wall clock
    pinned, so the assertion does not depend on when the suite runs.
    """
    predicate = DashboardRepository._vn_today_predicate("f.due_at").replace("now()", ":as_of")
    matched = await db.scalar(
        text(
            "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.status = 'PENDING' AND " + predicate + " AND l.lead_stage <> 'SKIPPED'"
        ),
        {"as_of": as_of},
    )
    return int(matched or 0) > 0


async def test_schedule_followup_is_due_at_nine_on_the_vietnam_calendar(monkeypatch) -> None:
    """The task comes due at 09:00 ICT tomorrow — inside the recruiter's morning —
    and the dashboard's counter already matches it on that Vietnam day."""
    from app.core.db import async_session

    # Realtime publishing is a transport seam, not part of this contract.
    monkeypatch.setattr(LeadEventBus, "lead_updated", AsyncMock())

    async with async_session() as setup:
        recruiter = await _recruiter(setup)
        lead = await _chatops_lead(setup)
        await setup.commit()
        lead_id, recruiter_id, start_version = lead.id, recruiter.id, lead.version

    async with async_session() as db:
        await LeadService(db).apply_chatops_action(
            await db.get(Lead, lead_id),
            "schedule_followup",
            actor=await db.get(User, recruiter_id),
        )

        followup = await db.scalar(select(FollowUpTask).where(FollowUpTask.lead_id == lead_id))
        assert followup.status == FollowupStatus.PENDING
        due_vn = followup.due_at.astimezone(_VN)
        assert (due_vn.hour, due_vn.minute) == (9, 0), (
            "the due morning is a Vietnam wall-clock hour; a UTC-anchored 09:00 "
            "lands at 16:00 ICT and never reaches the recruiter's morning"
        )
        assert due_vn.date() == datetime.now(_VN).date() + timedelta(days=1)
        assert followup.due_at.astimezone(timezone.utc).hour == 2

        # The lead write the recruiter sees is the same instant, versioned.
        written = await db.get(Lead, lead_id)
        assert written.next_action_at == followup.due_at
        assert written.version == start_version + 1

        # FOLLOWUP_TODAY matches the task from the recruiter's morning on the due
        # Vietnam day, and not before it.
        assert await _is_followup_today(db, as_of=due_vn.replace(hour=9, minute=30)) is True
        assert await _is_followup_today(db, as_of=due_vn - timedelta(days=1)) is False


async def test_schedule_followup_rejects_a_lead_another_recruiter_already_advanced(
    monkeypatch,
) -> None:
    """A lost race raises instead of writing: no next_action_at, no follow-up row."""
    from app.core.db import async_session

    monkeypatch.setattr(LeadEventBus, "lead_updated", AsyncMock())

    async with async_session() as setup:
        recruiter = await _recruiter(setup)
        lead = await _chatops_lead(setup)
        await setup.commit()
        lead_id, recruiter_id = lead.id, recruiter.id

    # The recruiter's assist panel still holds the lead at version 1 ...
    async with async_session() as stale:
        stale_lead = await stale.get(Lead, lead_id)
        assert stale_lead.version == 1

        # ... while a concurrent stage change commits version 2 underneath them.
        async with async_session() as racer:
            assert await LeadRepository(racer).optimistic_apply(lead_id, 1, version=2) is True
            await racer.commit()

        with pytest.raises(ConflictError):
            await LeadService(stale).apply_chatops_action(
                stale_lead, "schedule_followup", actor=await stale.get(User, recruiter_id)
            )
        await stale.rollback()

    async with async_session() as check:
        row = await check.get(Lead, lead_id)
        assert row.version == 2, "the refused action must not write its own version bump"
        assert row.next_action_at is None
        left_behind = await check.scalar(
            select(func.count()).select_from(FollowUpTask).where(FollowUpTask.lead_id == lead_id)
        )
        assert left_behind == 0, "a rejected action must not leave a follow-up behind"
