"""Eligibility scanner tests for proactive follow-up nudges.

Exercises ``find_eligible_conversations`` from
``app/services/proactive/repository.py`` — the SQL + Python gap filter that
selects BOT-mode, OPEN, interested-but-silent conversations within the Zalo
48-hour window.

Each test creates a Conversation + Lead pair with controlled attributes and
asserts whether the scanner returns it or not.
"""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from sqlalchemy import select

from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.lead import Lead, LeadScore, LeadStage
from app.services.proactive.repository import find_eligible_conversations

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)


async def _make_candidate(
    db,
    *,
    zalo_id: str,
    mode: str = "BOT",
    status: str = "OPEN",
    followup_count: int = 0,
    last_inbound_at: datetime | None = None,
    followup_opted_out: bool = False,
    last_followup_attempt_at: datetime | None = None,
    bot_locked_until: datetime | None = None,
    lead_stage: str = "NEW",
    lead_score: str | None = None,
    desired_job: str | None = None,
) -> Conversation:
    conv = Conversation(
        zalo_chat_id=zalo_id,
        mode=ConversationMode(mode),
        status=ConversationStatus(status),
        followup_count=followup_count,
        followup_opted_out=followup_opted_out,
        last_inbound_at=last_inbound_at,
        last_followup_attempt_at=last_followup_attempt_at,
        bot_locked_until=bot_locked_until,
    )
    db.add(conv)
    lead = Lead(
        zalo_id=zalo_id,
        name=f"Candidate {zalo_id}",
        lead_stage=LeadStage(lead_stage),
        lead_score=LeadScore(lead_score) if lead_score else None,
        desired_job=desired_job,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(conv)
    return conv


# ---- basic eligibility ----


@freeze_time(NOW)
async def test_eligible_basic(db_session, seed):
    """BOT+OPEN, recent inbound past gap[0]=6h, desired_job set → found."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-basic-1",
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id in ids


# ---- exclusion: mode / status / opted out ----


@freeze_time(NOW)
async def test_excluded_wrong_mode(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-mode-1",
        mode="HUMAN",
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


@freeze_time(NOW)
async def test_excluded_closed_status(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-closed-1",
        status="CLOSED",
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


@freeze_time(NOW)
async def test_excluded_opted_out(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-optout-1",
        followup_opted_out=True,
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: inbound timing ----


@freeze_time(NOW)
async def test_excluded_no_inbound(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-no-inbound-1",
        last_inbound_at=None,
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


@freeze_time(NOW)
async def test_excluded_past_48h(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-48h-1",
        last_inbound_at=NOW - timedelta(hours=50),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: cadence cap ----


@freeze_time(NOW)
async def test_excluded_cap_reached(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-cap-1",
        followup_count=3,
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: failed-send cooldown ----


@freeze_time(NOW)
async def test_excluded_recent_failed_attempt(db_session, seed):
    """last_followup_attempt_at within 6h cooldown → excluded."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-cool-1",
        last_inbound_at=NOW - timedelta(hours=7),
        last_followup_attempt_at=NOW - timedelta(hours=3),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


@freeze_time(NOW)
async def test_included_after_cooldown(db_session, seed):
    """last_followup_attempt_at older than 6h → included (if other criteria met)."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-cool-ok-1",
        last_inbound_at=NOW - timedelta(hours=7),
        last_followup_attempt_at=NOW - timedelta(hours=7),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id in ids


# ---- exclusion: lock held ----


@freeze_time(NOW)
async def test_excluded_locked(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-lock-1",
        last_inbound_at=NOW - timedelta(hours=7),
        bot_locked_until=NOW + timedelta(minutes=5),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: lead stage ----


@freeze_time(NOW)
async def test_excluded_lead_applied_stage(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-applied-1",
        last_inbound_at=NOW - timedelta(hours=7),
        lead_stage="APPLIED",
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: lead score ----


@freeze_time(NOW)
async def test_excluded_lead_not_interested(db_session, seed):
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-ni-1",
        last_inbound_at=NOW - timedelta(hours=7),
        lead_score="not_interested",
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- exclusion: no interest signal ----


@freeze_time(NOW)
async def test_excluded_no_interest_signal(db_session, seed):
    """No desired_job AND lead_score is NULL → excluded."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-noint-1",
        last_inbound_at=NOW - timedelta(hours=7),
        desired_job=None,
        lead_score=None,
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


@freeze_time(NOW)
async def test_included_warm_lead(db_session, seed):
    """lead_score=hot, no desired_job → included."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-warm-1",
        last_inbound_at=NOW - timedelta(hours=7),
        lead_score="hot",
        desired_job=None,
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id in ids


# ---- Python gap filter: slot not due ----


@freeze_time(NOW)
async def test_slot_not_due_yet(db_session, seed):
    """last_inbound_at only 2h ago, count=0, gap[0]=6h → not due yet."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-gap-1",
        last_inbound_at=NOW - timedelta(hours=2),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id not in ids


# ---- gap filter: slot 2 (46h) ----


@freeze_time(NOW)
async def test_slot_2_due(db_session, seed):
    """count=2 (gap[2]=46h), last_inbound_at=47h ago → due (within 48h + gap)."""
    conv = await _make_candidate(
        db_session,
        zalo_id="elig-slot2-1",
        followup_count=2,
        last_inbound_at=NOW - timedelta(hours=47),
        desired_job="Lái xe",
    )
    results = await find_eligible_conversations(db_session)
    ids = {c.id for c in results}
    assert conv.id in ids


# ---- per-tick cap ----


@freeze_time(NOW)
async def test_per_tick_cap(db_session, seed):
    """Only the first PROACTIVE_PER_TICK_CAP (5) candidates are returned."""
    for i in range(8):
        await _make_candidate(
            db_session,
            zalo_id=f"elig-cap-{i}",
            last_inbound_at=NOW - timedelta(hours=7),
            desired_job=f"Job {i}",
        )
    results = await find_eligible_conversations(db_session)
    assert len(results) <= 5
