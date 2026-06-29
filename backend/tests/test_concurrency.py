"""Tests for recruiter-vs-recruiter concurrency protection (Phase 1).

Pure unit tests with mocked DB sessions — no live database or Redis required.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.lead import Lead, LeadStage
from app.models.user import Role, User
from app.services.conversation.state import ConversationConflict, ConversationState
from app.services.lead_events import LeadEventBus
from app.services.lead_service import LeadConflict, LeadService
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


# --- LeadService optimistic concurrency tests ---

@pytest.mark.asyncio
async def test_lead_update_optimistic_conflict():
    """Lead update with stale version raises LeadConflict (rowcount=0)."""
    lead = _make_lead(id=1, version=1)
    db = AsyncMock()

    # Version check fails: rowcount=0
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    service = LeadService(db)
    with pytest.raises(LeadConflict):
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
    """Lead assign with stale version raises LeadConflict."""
    lead = _make_lead(id=1, version=2)
    recruiter = _make_user()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    service = LeadService(db)
    with pytest.raises(LeadConflict):
        await service.assign(lead, recruiter.id, actor=recruiter)


@pytest.mark.asyncio
async def test_lead_assign_success():
    """Lead assign with correct version succeeds."""
    lead = _make_lead(id=1, version=2)
    recruiter = _make_user()

    db = AsyncMock()
    # First execute: the atomic UPDATE (version check)
    db.execute = AsyncMock(return_value=FakeResult(rowcount=1))
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "assigned_recruiter_id", recruiter.id))
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
    """Lead set_stage with stale version raises LeadConflict."""
    lead = _make_lead(id=1, version=1)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult(rowcount=0))
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    service = LeadService(db)
    with pytest.raises(LeadConflict):
        await service.set_stage(lead, LeadStage.ENGAGED, actor=_make_user())


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


def test_lead_conflict_owner_name():
    """LeadConflict stores optional owner_name."""
    exc = LeadConflict("modified", owner_name="Bob")
    assert exc.owner_name == "Bob"
