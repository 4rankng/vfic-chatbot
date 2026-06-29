"""Integration tests for ``run_proactive_turn`` — the proactive follow-up pipeline.

Covers the 11-step turn: guard re-checks, 48h compliance, silence auto-opt-out,
lock acquisition, LLM decision (JSON), decision gate, safety gate, last-chance
guards, send, and persistence (``record_proactive_outcome``).

Real DB (postgres + pgvector via conftest's db_session) + fakes for the four
GraphDeps collaborators (agent / safety / zalo / embedder). ``build_system_prompt``
and ``LeadRepository.by_zalo_id`` are patched to keep the test focused on the
turn pipeline itself.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from sqlalchemy import select

from app.graph.proactive import run_proactive_turn
from app.graph.types import GraphDeps
from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.services.zalo_bot_service import SendResult

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes for GraphDeps collaborators
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_RESPONSE = (
    '{"send": true, '
    '"message": "Chào bạn, bạn có quan tâm đến vị trí này không?", '
    '"reason": "interested_lead"}'
)


class FakeAgent:
    """Returns a canned JSON decision string from ``agent(...)``."""

    def __init__(self, response: str = _DEFAULT_AGENT_RESPONSE) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def agent(self, text: str, **kw) -> str:
        self.calls.append({"text": text, "kw": kw})
        return self._response


class FakeSafety:
    """Returns a verdict JSON. Defaults to safe; inject ``unsafe=True`` for block tests.

    The proactive safety gate only invokes ``safety.safety`` when
    ``fast_safety_filter`` flags the candidate (empty / too long / risky keyword),
    so tests that want to exercise this path must craft a risky message too.
    """

    def __init__(self, unsafe: bool = False) -> None:
        self._unsafe = unsafe

    async def safety(self, text: str) -> str:
        if self._unsafe:
            return '{"safe_to_send": false, "issue_found": true, "final_answer": ""}'
        # When safe, echo back the candidate so it passes through unchanged.
        return (
            '{"safe_to_send": true, "issue_found": false, '
            '"final_answer": "' + text + '"}'
        )


class FakeZalo:
    def __init__(self, ok: bool = True, msg_id: str = "z-msg-1") -> None:
        self._ok = ok
        self._msg_id = msg_id
        self.calls: list[dict] = []

    async def send(self, chat_id: str, message: str) -> SendResult:
        self.calls.append({"chat_id": chat_id, "message": message})
        return SendResult(
            ok=self._ok,
            msg_id=self._msg_id if self._ok else None,
            error=None if self._ok else "Zalo 4xx",
        )


def _make_deps(db, agent=None, safety=None, zalo=None) -> GraphDeps:
    return GraphDeps(
        db=db,
        agent=agent or FakeAgent(),
        safety=safety or FakeSafety(),
        embedder=None,
        zalo=zalo or FakeZalo(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FROZEN = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)


async def _make_conv(db, zalo: str = "turn-1", **overrides) -> Conversation:
    """Seed a conversation. Defaults comply with every proactive guard."""
    defaults = dict(
        zalo_chat_id=zalo,
        mode=ConversationMode.BOT,
        status=ConversationStatus.OPEN,
        followup_count=0,
        followup_opted_out=False,
        version=1,
        # 1h ago — well inside the 48h window
        last_inbound_at=_FROZEN - timedelta(hours=1),
    )
    defaults.update(overrides)
    conv = Conversation(**defaults)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@contextlib.contextmanager
def _patch_context():
    """Patch ``build_system_prompt`` + ``LeadRepository`` for the turn.

    ``run_proactive_turn`` imports both lazily *inside* the function body, so
    patching ``app.graph.proactive.X`` does not work — we patch at the defining
    modules instead. The lead lookup returns ``None`` (no profile injection) to
    keep tests deterministic.
    """
    with patch(
        "app.graph.context.build_system_prompt",
        new=AsyncMock(return_value="system prompt"),
    ), patch("app.services.lead_repository.LeadRepository") as p_lead:
        p_lead.return_value.by_zalo_id = AsyncMock(return_value=None)
        yield


async def _fetch_messages(db, conv_id) -> list[Message]:
    res = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_happy_path_send(db_session):
    """Conv with fresh inbound + agent says send → outcome 'sent', message persisted."""
    conv = await _make_conv(db_session, zalo="happy")
    deps = _make_deps(db_session)

    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)

    await db_session.refresh(conv)
    assert outcome["outcome"] == "sent"
    assert outcome["reply"] == "Chào bạn, bạn có quan tâm đến vị trí này không?"

    # Message row
    msgs = await _fetch_messages(db_session, conv.id)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.sender == MessageSender.BOT
    assert m.bot_run_id is None
    assert m.delivery_status == DeliveryStatus.SENT
    assert m.zalo_message_id == "z-msg-1"
    assert m.external_error is None
    assert m.body == outcome["reply"]

    # Cadence bookkeeping
    assert conv.followup_count == 1
    assert conv.last_followup_at is not None
    # Lock released after the turn
    assert conv.bot_locked_until is None


# ---------------------------------------------------------------------------
# Guard suppressions (step 1)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_suppressed_opted_out(db_session):
    conv = await _make_conv(db_session, zalo="opted", followup_opted_out=True)
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "opted_out"
    assert conv.followup_count == 0
    assert not deps.zalo.calls  # no send attempt


@freeze_time(_FROZEN)
async def test_suppressed_cap_reached(db_session):
    # Default cap = 3
    conv = await _make_conv(db_session, zalo="cap", followup_count=3)
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "cap_reached"
    assert conv.followup_count == 3  # unchanged
    assert not deps.zalo.calls


@freeze_time(_FROZEN)
async def test_suppressed_locked(db_session):
    conv = await _make_conv(
        db_session,
        zalo="locked",
        bot_locked_until=_FROZEN + timedelta(minutes=5),
    )
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "locked"
    assert not deps.zalo.calls


@freeze_time(_FROZEN)
async def test_suppressed_no_inbound(db_session):
    conv = await _make_conv(db_session, zalo="no-inbound", last_inbound_at=None)
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "no_inbound"
    assert not deps.zalo.calls


@freeze_time(_FROZEN)
async def test_suppressed_wrong_mode(db_session):
    conv = await _make_conv(db_session, zalo="human-mode", mode=ConversationMode.HUMAN)
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    # mode/status share a single guard branch
    assert outcome["reason"] == "mode/status"
    assert not deps.zalo.calls


@freeze_time(_FROZEN)
async def test_suppressed_closed_status(db_session):
    conv = await _make_conv(db_session, zalo="closed", status=ConversationStatus.CLOSED)
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "mode/status"
    assert not deps.zalo.calls


# ---------------------------------------------------------------------------
# 48h window (step 2)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_suppressed_48h_window(db_session):
    # 48h ago exceeds the 47h margin (default proactive_48h_margin_seconds=3600).
    conv = await _make_conv(
        db_session,
        zalo="too-old",
        last_inbound_at=_FROZEN - timedelta(hours=48),
    )
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "48h_window"
    assert conv.followup_count == 0  # unchanged
    assert not deps.zalo.calls


# ---------------------------------------------------------------------------
# Decision gate (step 7)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_decision_send_false(db_session):
    conv = await _make_conv(db_session, zalo="decline")
    agent = FakeAgent(response='{"send": false, "message": "", "reason": "not_interested"}')
    deps = _make_deps(db_session, agent=agent)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "not_interested"
    assert conv.followup_count == 0  # declined -> no cadence budget consumed
    assert not deps.zalo.calls


@freeze_time(_FROZEN)
async def test_decision_empty_message(db_session):
    conv = await _make_conv(db_session, zalo="empty-msg")
    agent = FakeAgent(response='{"send": true, "message": "", "reason": "blank"}')
    deps = _make_deps(db_session, agent=agent)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "empty_message"
    assert conv.followup_count == 0
    assert not deps.zalo.calls


# ---------------------------------------------------------------------------
# Safety gate (step 8)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_safety_blocked(db_session):
    """``fast_safety_filter`` flags a risky keyword → LLM safety says unsafe → suppress.

    The fast filter only routes to the LLM safety model when the candidate matches
    ``_RISK_RE`` (or is empty / >1800 chars). So we craft a message containing a
    risky term to force the ``needs_llm_safety=True`` branch, then FakeSafety
    returns ``safe_to_send: false``.
    """
    # Craft a message that triggers ``_RISK_RE`` in ``app.graph.safety`` so
    # ``fast_safety_filter`` routes it to the LLM safety model. The regex flags
    # technical/code-leakage tokens (workflow, node, code, sql, api, ...); we use
    # a JSON-safe word so the agent's JSON decision still parses correctly.
    risky_message = "Đây là workflow code internal SQL api cho bạn."
    agent = FakeAgent(
        response='{"send": true, "message": "' + risky_message + '", "reason": "x"}'
    )
    safety = FakeSafety(unsafe=True)
    conv = await _make_conv(db_session, zalo="unsafe")
    deps = _make_deps(db_session, agent=agent, safety=safety)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)

    # If the fast filter did not flag the message, safety.safety is never called
    # and the message is sent — assert safety was consulted, else fail with a
    # clear message so the test is not silently vacuous.
    assert safety.safety.__wrapped__ if hasattr(safety.safety, "__wrapped__") else True
    # We verify via outcome: either suppressed (safety gate fired) or — if the
    # regex did not match — the test's premise failed.
    if outcome["outcome"] == "sent":
        pytest.fail(
            "risky message was not routed to LLM safety (fast_safety_filter did not "
            "flag it); tighten risky_message to match app.graph.safety._RISK_RE"
        )
    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "safety_blocked"
    assert conv.followup_count == 0
    assert not deps.zalo.calls


# ---------------------------------------------------------------------------
# Send failure (step 10 → 11)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_send_failure(db_session):
    """Zalo returns ok=False → message FAILED, cadence NOT consumed, attempt stamped."""
    conv = await _make_conv(db_session, zalo="zalo-fail")
    zalo = FakeZalo(ok=False)
    deps = _make_deps(db_session, zalo=zalo)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)

    assert outcome["outcome"] == "send_failed"
    # Cadence budget not consumed on failure
    assert conv.followup_count == 0
    # Attempt timestamp recorded
    assert conv.last_followup_attempt_at is not None
    # last_followup_at only set on success
    assert conv.last_followup_at is None
    # Lock released despite failure
    assert conv.bot_locked_until is None

    msgs = await _fetch_messages(db_session, conv.id)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.sender == MessageSender.BOT
    assert m.delivery_status == DeliveryStatus.FAILED
    assert m.zalo_message_id is None
    assert m.external_error == "Zalo 4xx"
    assert m.bot_run_id is None


# ---------------------------------------------------------------------------
# Silence auto-opt-out (step 3)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_silence_optout(db_session):
    """2 prior nudges + no WORKER reply since last_followup_at → auto opt-out."""
    conv = await _make_conv(
        db_session,
        zalo="silent",
        followup_count=2,
        # Last nudge 3h ago; no worker reply between then and now.
        last_followup_at=_FROZEN - timedelta(hours=3),
    )
    deps = _make_deps(db_session)
    with _patch_context():
        outcome = await run_proactive_turn(conv, deps)
    await db_session.refresh(conv)

    assert outcome["outcome"] == "proactive:suppressed"
    assert outcome["reason"] == "silence_optout"
    # Auto opt-out persisted
    assert conv.followup_opted_out is True
    # No send attempted
    assert not deps.zalo.calls
    # Cadence count unchanged (silence does not consume budget either)
    assert conv.followup_count == 2


# ---------------------------------------------------------------------------
# Dedup via lock (step 4)
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN)
async def test_duplicate_dedup(db_session):
    """A turn that already holds the lock suppresses a concurrent second turn."""
    conv = await _make_conv(db_session, zalo="dedup")
    deps = _make_deps(db_session)

    with _patch_context():
        first = await run_proactive_turn(conv, deps)
        # After the first turn the lock is released by record_proactive_outcome;
        # to exercise the "lock already held" branch we re-acquire the lock
        # manually (simulating a concurrent in-flight reactive turn) and rerun.
        from app.services.conversation import ConversationService

        svc = ConversationService(deps.db)
        acquired = await svc.acquire_lock(conv.id)
        assert acquired is True

        second = await run_proactive_turn(conv, deps)

    assert first["outcome"] == "sent"
    # Second turn sees bot_locked_until in the future at guard step 1.
    assert second["outcome"] == "proactive:suppressed"
    assert second["reason"] == "locked"
