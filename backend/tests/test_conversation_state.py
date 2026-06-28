"""Phase 2 characterization tests for ConversationService state methods.

Locks the behavior of the previously under-covered mutations (ensure, acquire_lock,
recheck_ownership, record_bot_outcome, close/reopen) so the services/conversation/
split (repository + state + events facade) cannot regress them. Exercises the public
ConversationService facade — which also validates the delegation wiring.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    MessageSender,
)
from app.models.user import User
from app.services.conversation import ConversationService
from tests.conftest import RECRUITER_EMAIL

pytestmark = pytest.mark.asyncio


async def _make_conv(db_session, zalo="state-1") -> Conversation:
    conv = Conversation(zalo_chat_id=zalo)
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


async def _recruiter(db_session) -> User:
    return (await db_session.scalars(select(User).where(User.email == RECRUITER_EMAIL))).first()


# --------------------------------------------------------------------------- ensure
async def test_ensure_creates_then_returns_existing(db_session, seed):
    svc = ConversationService(db_session)
    c1 = await svc.ensure("zalo-ensure-1")
    c2 = await svc.ensure("zalo-ensure-1")
    assert c1.id == c2.id  # idempotent — second call returns the same row
    n = (
        await db_session.scalars(
            select(Conversation).where(Conversation.zalo_chat_id == "zalo-ensure-1")
        )
    ).all()
    assert len(n) == 1


# --------------------------------------------------------------------- acquire_lock
async def test_acquire_lock_mutual_exclusion_and_expiry(db_session, seed):
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, zalo="lock-1")

    assert await svc.acquire_lock(conv.id) is True  # first acquires
    assert await svc.acquire_lock(conv.id) is False  # second is blocked (within TTL)

    # Backdate the lock past the TTL window -> the mutex frees and re-acquire succeeds.
    await db_session.refresh(conv)
    conv.bot_locked_until = datetime.now(timezone.utc) - timedelta(seconds=60)
    await db_session.commit()
    assert await svc.acquire_lock(conv.id) is True


# ------------------------------------------------------------------ recheck_ownership
async def test_recheck_ownership_predicates(db_session, seed):
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, zalo="own-1")
    assert conv.mode == ConversationMode.BOT  # default
    v = conv.version

    assert await svc.recheck_ownership(conv, v) is True  # BOT + version match
    conv.version = v + 1
    assert await svc.recheck_ownership(conv, v) is False  # version changed
    conv.version = v
    conv.mode = ConversationMode.HUMAN
    assert await svc.recheck_ownership(conv, v) is False  # no longer BOT


async def test_semi_auto_guard_waits_for_five_minutes_of_human_inactivity(db_session, seed):
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, zalo="semi-guard-1")
    conv.mode = ConversationMode.SEMI_AUTO
    conv.taken_over_at = datetime.now(timezone.utc) - timedelta(minutes=4)
    await db_session.commit()
    await db_session.refresh(conv)

    assert svc.run_start_guard(conv) is False
    assert await svc.recheck_ownership(conv, conv.version) is False

    conv.taken_over_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    await db_session.commit()
    await db_session.refresh(conv)

    assert svc.run_start_guard(conv) is True
    assert await svc.recheck_ownership(conv, conv.version) is True


# ------------------------------------------------------------------ record_bot_outcome
async def test_record_bot_outcome_sent_and_suppressed(db_session, seed):
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, zalo="bot-1")
    await svc.acquire_lock(conv.id)
    # acquire_lock is a bulk UPDATE (synchronize_session=False); refresh so the
    # in-memory conv reflects the lock, the way the real caller (graph/runner) holds it.
    await db_session.refresh(conv)
    started = datetime.now(timezone.utc) - timedelta(seconds=1)

    sent = await svc.record_bot_outcome(
        conv, version_at_start=conv.version, reply="chào bạn", started_at=started, sent=True
    )
    assert sent.delivery_status == DeliveryStatus.SENT
    assert sent.sender == MessageSender.BOT
    runs = (await db_session.scalars(select(BotRun).where(BotRun.conversation_id == conv.id))).all()
    assert len(runs) == 1 and runs[0].outcome == BotRunOutcome.SENT
    await db_session.refresh(conv)
    assert conv.bot_locked_until is None  # lock cleared after outcome

    suppressed = await svc.record_bot_outcome(
        conv, version_at_start=conv.version, reply="(đã chặn)", started_at=started, sent=False
    )
    assert suppressed.delivery_status == DeliveryStatus.SUPPRESSED


# --------------------------------------------------------------------- close / reopen
async def test_close_and_reopen_transition_modes(db_session, seed):
    svc = ConversationService(db_session)
    recruiter = await _recruiter(db_session)
    conv = await _make_conv(db_session, zalo="cr-1")
    v = conv.version

    await svc.close(conv, recruiter)
    await db_session.refresh(conv)
    assert conv.mode == ConversationMode.CLOSED
    assert conv.status == ConversationStatus.CLOSED
    assert conv.version == v + 1

    await svc.reopen(conv, recruiter)
    await db_session.refresh(conv)
    assert conv.mode == ConversationMode.BOT
    assert conv.status == ConversationStatus.OPEN
    assert conv.version == v + 2
