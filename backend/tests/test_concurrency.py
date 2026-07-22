"""Tests for recruiter-vs-recruiter concurrency protection (Phase 1).

Pure unit tests with mocked DB sessions — no live database or Redis required.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.lead import Lead, LeadStage
from app.models.user import Role, User
from app.services.conversation.state import ConversationConflict, ConversationState, utcnow
from app.services.errors import ConflictError
from app.services.lead import LeadService
from app.services.presence import _get_viewers, join_viewing, leave_viewing


# --- helpers ---


def _make_conv(
    *,
    id: uuid.UUID | None = None,
    assigned_recruiter_id: uuid.UUID | None = None,
    mode: ConversationMode = ConversationMode.BOT,
    status: ConversationStatus = ConversationStatus.OPEN,
    version: int = 1,
) -> Conversation:
    conv = Conversation(
        zalo_chat_id="test-zalo-id",
        assigned_recruiter_id=assigned_recruiter_id,
        mode=mode,
        status=status,
        version=version,
    )
    if id is not None:
        conv.id = id
    else:
        conv.id = uuid.uuid4()
    return conv


def _make_user(*, id: uuid.UUID | None = None, name: str = "Test User") -> User:
    user = User(
        full_name=name,
        email=f"{name.lower().replace(' ', '')}@test.com",
        role=Role.admin,
    )
    if id is not None:
        user.id = id
    else:
        user.id = uuid.uuid4()
    return user


def _make_lead(*, id: int = 1, version: int = 1) -> Lead:
    lead = Lead(
        zalo_id="test-zalo-id",
        name="Test Lead",
        lead_stage=LeadStage.NEW,
        version=version,
    )
    lead.id = id
    return lead


@dataclass
class FakeResult:
    """Minimal mock of SQLAlchemy Result with rowcount."""

    rowcount: int = 0
    _scalar_return: object | None = None

    def scalar(self):
        return self._scalar_return

    def scalar_one_or_none(self):
        return self._scalar_return

    def first(self):
        return self._scalar_return


@dataclass
class FakeRefreshMixin:
    """Mixin providing db.refresh that copies attributes from a fresh dict."""

    _fresh_data: dict = field(default_factory=dict)

    async def refresh(self, obj) -> None:
        for k, v in self._fresh_data.items():
            if hasattr(obj, k):
                setattr(obj, k, v)


# --- ConversationState tests ---


@pytest.mark.asyncio
async def test_extracted_intent_handoff_is_atomic_and_emits_after_commit(monkeypatch):
    conv = _make_conv()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(_scalar_return=2))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", audit)
    events = AsyncMock()

    transitioned = await ConversationState(db, MagicMock(), events).escalate_extracted_intent(
        conv,
        reason="bot_testing",
        confidence=0.98765,
        expected_version=1,
    )

    assert transitioned is True
    params = db.execute.await_args.args[0].compile().params
    assert params["mode"] == ConversationMode.HUMAN
    assert params["status"] == ConversationStatus.OPEN
    assert params["needs_human"] is True
    assert params["bot_locked_until"] is None
    audit.assert_awaited_once_with(
        db,
        action="extraction_intent_human_review",
        target_type="conversation",
        target_id=str(conv.id),
        payload={"reason": "bot_testing", "confidence": 0.9877, "version": 2},
    )
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    events.message_created.assert_awaited_once()
    events.conversation_updated.assert_awaited_once_with(conv)


@pytest.mark.asyncio
async def test_extracted_intent_handoff_is_idempotent(monkeypatch):
    conv = _make_conv(mode=ConversationMode.HUMAN)
    conv.needs_human = True
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(_scalar_return=None))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", audit)
    events = AsyncMock()

    transitioned = await ConversationState(db, MagicMock(), events).escalate_extracted_intent(
        conv,
        reason="spam",
        confidence=0.99,
        expected_version=1,
    )

    assert transitioned is False
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    audit.assert_not_awaited()
    events.message_created.assert_not_awaited()
    events.conversation_updated.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "needs_human"),
    [
        (ConversationMode.BOT, True),
        (ConversationMode.HUMAN, False),
    ],
)
async def test_extracted_intent_handoff_repairs_partial_review_state(
    monkeypatch,
    mode,
    needs_human,
):
    conv = _make_conv(mode=mode)
    conv.needs_human = needs_human
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(_scalar_return=2))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", AsyncMock())

    transitioned = await ConversationState(
        db, MagicMock(), AsyncMock()
    ).escalate_extracted_intent(
        conv,
        reason="non_candidate",
        confidence=0.96,
        expected_version=1,
    )

    assert transitioned is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_take_over_success_when_unassigned():
    """take_over succeeds when conversation is unassigned (rowcount=1)."""
    conv = _make_conv()
    recruiter = _make_user()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    db.refresh = AsyncMock(side_effect=lambda obj: None)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    events = AsyncMock()
    repo = MagicMock()
    state = ConversationState(db, repo, events)

    result = await state.take_over(conv, recruiter)

    assert result is conv
    assert db.execute.call_count == 1
    db.commit.assert_called()
    assert db.add.call_count >= 1  # system message (+ audit event)
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_take_over_success_when_already_owner():
    """take_over succeeds idempotently when same recruiter re-claims (rowcount=1)."""
    rid = uuid.uuid4()
    conv = _make_conv(assigned_recruiter_id=rid)
    recruiter = _make_user(id=rid)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    events = AsyncMock()
    state = ConversationState(db, MagicMock(), events)
    result = await state.take_over(conv, recruiter)

    assert result is conv


@pytest.mark.asyncio
async def test_take_over_conflict_when_owned_by_other():
    """take_over raises ConversationConflict when owned by another (rowcount=0)."""
    owner_id = uuid.uuid4()
    conv = _make_conv(assigned_recruiter_id=owner_id)
    recruiter = _make_user()
    owner_name = "Nguyen Van A"

    # First execute: the atomic UPDATE fails (rowcount=0)
    # Second execute: the refresh fetches the owner name via db.scalar
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            FakeResult(rowcount=0),  # atomic UPDATE fails
        ]
    )
    db.scalar = AsyncMock(return_value=owner_name)  # owner name lookup
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "assigned_recruiter_id", owner_id))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    events = AsyncMock()
    state = ConversationState(db, MagicMock(), events)

    with pytest.raises(ConversationConflict) as exc_info:
        await state.take_over(conv, recruiter)

    assert exc_info.value.owner_name == owner_name


@pytest.mark.asyncio
async def test_semi_auto_conflict_when_owned_by_other():
    """semi_auto raises ConversationConflict when owned by another (rowcount=0)."""
    owner_id = uuid.uuid4()
    conv = _make_conv(assigned_recruiter_id=owner_id)
    recruiter = _make_user()

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            FakeResult(rowcount=0),
        ]
    )
    db.scalar = AsyncMock(return_value="Owner Name")
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "assigned_recruiter_id", owner_id))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    state = ConversationState(db, MagicMock(), AsyncMock())

    with pytest.raises(ConversationConflict) as exc_info:
        await state.semi_auto(conv, recruiter)

    assert exc_info.value.owner_name == "Owner Name"


@pytest.mark.asyncio
async def test_record_bot_pending_does_not_bump_version():
    conv = _make_conv(version=7)

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    events = MagicMock()
    state = ConversationState(db, MagicMock(), events)

    msg = await state.record_bot_pending(conv)

    assert msg.sender == MessageSender.BOT
    assert msg.delivery_status == DeliveryStatus.PENDING
    assert conv.version == 7
    # record_bot_pending schedules fire-and-forget realtime: payloads are
    # serialized eagerly on this coroutine and only the Redis publishes are
    # deferred to a background task (keeps the post-commit fan-out off the
    # webhook-ack / db_ms hot path). schedule_realtime is synchronous, so assert
    # the call rather than an await.
    events.schedule_realtime.assert_called_once_with(msg, conv)


@pytest.mark.asyncio
async def test_schedule_realtime_publishes_prebuilt_payloads_off_greenlet(monkeypatch):
    """Regression guard for the MissingGreenlet / PendingRollback crash.

    The background task must only Redis-publish already-serialized dicts.
    Touching the (post-commit-expired, session-bound) ORM objects from the
    background task raises MissingGreenlet and poisons the shared session
    (PendingRollbackError cascade). Payloads are therefore built eagerly on the
    caller's coroutine and the task publishes those plain dicts.
    """
    from types import SimpleNamespace

    from app.services.conversation import events as events_mod

    published: list[tuple[str, object]] = []

    async def fake_publish(channel, payload):
        published.append((channel, payload))

    monkeypatch.setattr(events_mod, "publish_event", fake_publish)
    monkeypatch.setattr(events_mod, "_message_payload", lambda _msg: {"msg": "serialized"})
    monkeypatch.setattr(events_mod, "_conv_payload", lambda _conv: {"conv": "serialized"})

    bus = events_mod.ConversationEventBus(db=object())
    msg = SimpleNamespace(id=42)
    conv = SimpleNamespace(id="conv-7")

    bus.schedule_realtime(msg, conv)
    assert len(events_mod._background_tasks) == 1
    # Payloads are built synchronously before the task runs, so nothing is
    # published until the loop is pumped.
    assert published == []
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert published == [
        (
            "message.created",
            {"message_id": 42, "conversation_id": "conv-7", "message": {"msg": "serialized"}},
        ),
        ("conversation.updated", {"conv": "serialized"}),
    ]
    assert events_mod._background_tasks == set()


@pytest.mark.asyncio
async def test_record_bot_outcome_updates_pending_message_in_place():
    conv = _make_conv(version=3)
    pending = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body="Đang soạn trả lời...",
        delivery_status=DeliveryStatus.PENDING,
    )
    pending.id = 42

    db = AsyncMock()
    db.add = MagicMock()

    async def _flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "proposed_reply"):
                obj.id = 99

    db.flush = AsyncMock(side_effect=_flush)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=pending)
    events = AsyncMock()
    state = ConversationState(db, MagicMock(), events)

    msg = await state.record_bot_outcome(
        conv,
        version_at_start=3,
        reply="Câu trả lời cuối cùng",
        started_at=utcnow(),
        sent=True,
        pending_message_id=42,
    )

    assert msg is pending
    assert pending.body == "Câu trả lời cuối cùng"
    assert pending.delivery_status == DeliveryStatus.SENT
    assert pending.bot_run_id is not None
    assert conv.bot_locked_until is None
    assert conv.last_outbound_at is not None
    events.message_created.assert_awaited_once()
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_bot_outcome_transitions_sending_row_in_place():
    """A SENDING row (flipped by claim_send) is matched and transitioned to its
    final state IN PLACE — not left dangling, and not duplicated as a second
    message. This is the outcome-side half of the no-duplicate guarantee:
    record_bot_outcome accepts SENDING (not only PENDING) in the pending-match."""
    conv = _make_conv(version=3)
    sending = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body="Trả lời thật",  # claim_send already stamped the real reply
        delivery_status=DeliveryStatus.SENDING,
    )
    sending.id = 42

    db = AsyncMock()
    db.add = MagicMock()

    async def _flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "proposed_reply"):
                obj.id = 99

    db.flush = AsyncMock(side_effect=_flush)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=sending)
    events = AsyncMock()
    state = ConversationState(db, MagicMock(), events)

    msg = await state.record_bot_outcome(
        conv,
        version_at_start=3,
        reply="Trả lời thật",
        started_at=utcnow(),
        sent=True,
        pending_message_id=42,
    )

    # In-place transition: the SENDING row becomes the SENT row, not a duplicate.
    assert msg is sending
    assert sending.delivery_status == DeliveryStatus.SENT
    assert sending.body == "Trả lời thật"
    assert sending.bot_run_id is not None
    assert conv.bot_locked_until is None
    assert conv.last_outbound_at is not None
    events.message_created.assert_awaited_once()
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_recheck_ownership_requires_matching_live_lock_owner():
    conv = _make_conv(version=3)
    owner = uuid.uuid4()
    conv.bot_lock_owner = owner
    conv.bot_locked_until = utcnow() + timedelta(seconds=30)

    state = ConversationState(AsyncMock(), MagicMock(), AsyncMock())

    assert await state.recheck_ownership(conv, 3, lock_owner=owner)
    assert not await state.recheck_ownership(conv, 3, lock_owner=uuid.uuid4())

    conv.bot_locked_until = utcnow() - timedelta(seconds=1)
    assert not await state.recheck_ownership(conv, 3, lock_owner=owner)


@pytest.mark.asyncio
async def test_claim_send_requires_pending_row_and_lock_owner():
    """claim_send refuses to claim without a pending BOT row or a lock owner — the
    atomic claim's preconditions. A real turn always holds both; missing either
    means the caller suppresses rather than sending without a durable marker."""
    conv = _make_conv(version=3)
    db = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    assert not await state.claim_send(
        conv,
        version_at_start=3,
        lock_owner=uuid.uuid4(),
        pending_message_id=None,
        reply="Trả lời thật",
    )
    assert not await state.claim_send(
        conv,
        version_at_start=3,
        lock_owner=None,
        pending_message_id=42,
        reply="Trả lời thật",
    )
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_claim_send_gates_on_version_and_lock_owner_in_one_statement():
    """The claim is one conditional UPDATE: rowcount==1 ⇒ still owned at
    version_at_start with a live lock owned by lock_owner (send); 0 ⇒ a takeover
    or newer inbound bumped version first (suppress). The WHERE EXISTS on the
    conversation closes the recheck→send TOCTOU server-side, not read-then-act."""
    conv = _make_conv(version=3)
    owner = uuid.uuid4()
    db = AsyncMock()
    db.commit = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    assert await state.claim_send(
        conv,
        version_at_start=3,
        lock_owner=owner,
        pending_message_id=42,
        reply="Trả lời thật",
    )

    sql = str(db.execute.call_args[0][0])
    params = db.execute.call_args[0][1]
    assert "UPDATE messages SET delivery_status = 'SENDING', body = :reply" in sql
    assert "EXISTS" in sql
    assert "c.version = :version_at_start" in sql
    assert "c.bot_lock_owner = :owner" in sql
    assert "c.bot_locked_until > now()" in sql
    assert params == {
        "pending_id": 42,
        "cid": conv.id,
        "version_at_start": 3,
        "owner": owner,
        "reply": "Trả lời thật",
    }

    # rowcount 0 ⇒ not claimed (suppress); a recruiter reply bumped version, etc.
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    assert not await state.claim_send(
        conv,
        version_at_start=3,
        lock_owner=owner,
        pending_message_id=42,
        reply="Trả lời thật",
    )


@pytest.mark.asyncio
async def test_break_stale_lock_reports_whether_a_stale_lock_broke():
    """break_stale_lock force-clears a mutex whose owner heartbeat is stale; the
    conditional WHERE means a live turn with a fresh heartbeat is never stolen.
    rowcount reports whether a stale lock was actually broken."""
    conv = _make_conv()
    db = AsyncMock()
    db.commit = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    assert await state.break_stale_lock(conv.id, stale_after_seconds=60)
    sql = str(db.execute.call_args[0][0])
    assert "bot_lock_heartbeat_at" in sql

    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    assert not await state.break_stale_lock(conv.id, stale_after_seconds=60)


@pytest.mark.asyncio
async def test_resolve_unconfirmed_sending_marks_delivery_unknown_without_retrying():
    """A stuck SENDING row becomes SEND_UNKNOWN, never silently SENT or retried."""
    conv = _make_conv()
    db = AsyncMock()
    db.commit = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    # A SENDING row moved → message UPDATE + matching outbox terminal update.
    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    assert await state.resolve_unconfirmed_sending(conv.id) == 1
    assert db.execute.await_count == 2

    # No SENDING row → only the message UPDATE.
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    assert await state.resolve_unconfirmed_sending(conv.id) == 0
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_release_lock_does_not_clear_mismatched_owner():
    conv = _make_conv(version=3)
    current_owner = uuid.uuid4()
    conv.bot_lock_owner = current_owner
    conv.bot_locked_until = utcnow() + timedelta(seconds=30)
    conv.bot_lock_heartbeat_at = utcnow()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.commit = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    await state.release_lock(conv, lock_owner=uuid.uuid4())

    assert conv.bot_lock_owner == current_owner
    assert conv.bot_locked_until is not None
    assert conv.bot_lock_heartbeat_at is not None


@pytest.mark.asyncio
async def test_record_bot_outcome_does_not_clear_mismatched_owner():
    conv = _make_conv(version=3)
    current_owner = uuid.uuid4()
    conv.bot_lock_owner = current_owner
    conv.bot_locked_until = utcnow() + timedelta(seconds=30)
    conv.bot_lock_heartbeat_at = utcnow()

    db = AsyncMock()
    db.add = MagicMock()

    async def _flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "proposed_reply"):
                obj.id = 99

    db.flush = AsyncMock(side_effect=_flush)
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=None)
    state = ConversationState(db, MagicMock(), AsyncMock())

    await state.record_bot_outcome(
        conv,
        version_at_start=3,
        reply="Câu trả lời cuối cùng",
        started_at=utcnow(),
        sent=True,
        lock_owner=uuid.uuid4(),
    )

    assert conv.bot_lock_owner == current_owner
    assert conv.bot_locked_until is not None
    assert conv.bot_lock_heartbeat_at is not None
    assert conv.last_outbound_at is not None


# --- LeadService optimistic concurrency tests ---


@pytest.mark.asyncio
async def test_lead_update_optimistic_conflict():
    """Lead update with stale version raises ConflictError (rowcount=0)."""
    lead = _make_lead(id=1, version=1)
    db = AsyncMock()

    # Version check fails: rowcount=0
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    service = LeadService(db)
    with pytest.raises(ConflictError):
        await service.update(lead, {"version": 1, "name": "New Name"})


@pytest.mark.asyncio
async def test_lead_update_success_with_version():
    """Lead update with correct version succeeds (rowcount=1)."""
    lead = _make_lead(id=1, version=1)
    db = AsyncMock()

    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "name", "New Name"))
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    events = AsyncMock()
    service = LeadService(db)
    service.events = events

    result = await service.update(lead, {"version": 1, "name": "New Name"})

    assert result.name == "New Name"
    events.lead_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_lead_update_without_version_skips_check():
    """Lead update without version field falls through to direct setattr."""
    lead = _make_lead(id=1, version=1)
    db = AsyncMock()

    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    events = AsyncMock()
    service = LeadService(db)
    service.events = events

    result = await service.update(lead, {"name": "Direct Name"})

    assert result.name == "Direct Name"
    # execute should NOT have been called (no version guard)
    db.execute.assert_not_called()
    events.lead_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_lead_assign_optimistic_conflict():
    """Lead assign with stale version raises ConflictError."""
    lead = _make_lead(id=1, version=2)
    recruiter = _make_user()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    service = LeadService(db)
    with pytest.raises(ConflictError):
        await service.assign(lead, recruiter.id, actor=recruiter)


@pytest.mark.asyncio
async def test_lead_assign_success():
    """Lead assign with correct version succeeds."""
    lead = _make_lead(id=1, version=2)
    recruiter = _make_user()

    db = AsyncMock()
    # First execute: the atomic UPDATE (version check)
    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    db.refresh = AsyncMock(
        side_effect=lambda obj: setattr(obj, "assigned_recruiter_id", recruiter.id)
    )
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    events = AsyncMock()
    service = LeadService(db)
    service.events = events

    result = await service.assign(lead, recruiter.id, actor=recruiter)

    assert result.assigned_recruiter_id == recruiter.id
    events.lead_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_lead_set_stage_optimistic_conflict():
    """Lead set_stage with stale version raises ConflictError."""
    lead = _make_lead(id=1, version=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    service = LeadService(db)
    with pytest.raises(ConflictError):
        await service.set_stage(lead, LeadStage.CONTACTING, actor=_make_user())


# --- Presence tests (mocked Redis) ---


@pytest.mark.asyncio
async def test_presence_join_leave():
    """join_viewing adds a viewer; leave_viewing removes them."""
    mock_redis = AsyncMock()
    mock_redis.sadd = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.smembers = AsyncMock(return_value=set())
    mock_redis.srem = AsyncMock()

    mock_emit = AsyncMock()

    with (
        patch("app.services.presence.get_redis", return_value=mock_redis),
        patch("app.services.presence.emit_event", side_effect=mock_emit),
    ):
        # Join
        await join_viewing("lead", 1, "user-1", "Alice")
        mock_redis.sadd.assert_called_once()
        mock_redis.expire.assert_called_once()

        # Leave
        mock_redis.smembers.return_value = {b'{"user_id": "user-1", "name": "Alice"}'}
        await leave_viewing("lead", 1, "user-1")
        mock_redis.srem.assert_called_once()


@pytest.mark.asyncio
async def test_get_viewers_parses_json():
    """_get_viewers correctly parses JSON SET members."""
    mock_redis = MagicMock()
    mock_redis.smembers = AsyncMock(
        return_value={b'{"user_id": "u1", "name": "Alice"}', b"invalid-json"}
    )

    viewers = await _get_viewers(mock_redis, "test-key")
    assert len(viewers) == 1
    assert viewers[0]["user_id"] == "u1"
    assert viewers[0]["name"] == "Alice"


# --- ConversationConflict carries owner_name ---


def test_conversation_conflict_owner_name():
    """ConversationConflict stores optional owner_name."""
    exc1 = ConversationConflict("taken")
    assert exc1.owner_name is None

    exc2 = ConversationConflict("taken", owner_name="Alice")
    assert exc2.owner_name == "Alice"
    assert str(exc2) == "taken"


def test_conflict_error_message():
    exc = ConflictError("modified")
    assert str(exc) == "modified"
