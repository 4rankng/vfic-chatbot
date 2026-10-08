"""The recruiter-triggered review turn: read the conversation, reply only if needed.

``POST /conversations/{id}/bot-reply`` is the lever for the threads
``force-bot-reply`` cannot reach — every inbound already carries a reply, yet the
candidate is still waiting on a real answer. The turn reuses the normal pipeline
with no inbound of its own, so these tests pin the three things that make it
different: the job it enqueues, the directive that replaces the candidate's
message, and the deliberate silence that must send nothing at all.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.graph.manual_reply import (
    MANUAL_REPLY_INSTRUCTION,
    manual_instruction_for,
    manual_skip_requested,
)
from app.graph.prompt_context import build_agent_user_text
from app.graph.types import BotRunState

CONV_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
CONV_ID = str(CONV_UUID)

# The scheduler is the only producer of the manual job; the route test below
# pins the flag it sets, this file pins what the flag means.
pytestmark = pytest.mark.timeout(30)


def _manual_state(**overrides) -> BotRunState:
    state = BotRunState(
        conversation_id=CONV_ID,
        version_at_start=3,
        user_text="",
        lock_owner="owner-1",
        manual_instruction=MANUAL_REPLY_INSTRUCTION,
    )
    for name, value in overrides.items():
        setattr(state, name, value)
    return state


class _LaneAgent:
    """Stands in for ``_agent_turn`` and records what the lane handed it."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.kwargs: dict | None = None
        self.user_text: str | None = None

    async def __call__(self, state, deps, user_text, **kwargs):  # noqa: ARG002
        self.kwargs = kwargs
        self.user_text = user_text
        return self.reply


def _deps() -> SimpleNamespace:
    db = AsyncMock()
    return SimpleNamespace(db=db, conversation=object(), turn_decisions=None)


def _svc() -> SimpleNamespace:
    return SimpleNamespace(record_bot_outcome=AsyncMock(return_value=True))


async def _resolve_lane(agent: _LaneAgent, *, project_context=None, state=None):
    from app.graph.lanes import _resolve_lane
    from app.graph.ports import TurnDecisions

    return await _resolve_lane(
        state=state or _manual_state(),
        deps=_deps(),
        conv=SimpleNamespace(contact_id=None),
        svc=_svc(),
        decisions=TurnDecisions(intent="general", intent_confidence=0.9),
        turn_route=SimpleNamespace(intent="general", reason="empty", confidence=0.1),
        project_context=project_context,
        recent_messages=[],
        manifest_policy=None,
        provider="zalo_bot",
        recipient_id="u1",
        timings={},
        started="2026-10-08T00:00:00+00:00",
        lock_owner="owner-1",
        status_task=None,
        t0=0.0,
        agent_turn=agent,
    )


# --- the directive -----------------------------------------------------------


def test_a_flagged_job_resolves_to_the_directive_and_a_plain_one_does_not() -> None:
    assert manual_instruction_for(True) == MANUAL_REPLY_INSTRUCTION
    for unflagged in (False, None, 0, ""):
        assert manual_instruction_for(unflagged) == ""


def test_the_directive_tells_the_agent_staying_silent_is_allowed() -> None:
    # The skip is only meaningful if the model is told it may stay silent, and
    # told the exact string that silence means.
    assert "KHÔNG gửi" in MANUAL_REPLY_INSTRUCTION
    assert "NO_REPLY" in MANUAL_REPLY_INSTRUCTION


@pytest.mark.parametrize(
    "reply",
    [
        "NO_REPLY",
        "no_reply",
        "  **NO_REPLY**  ",
        "`NO_REPLY`",
        "NO_REPLY.",
        "NO_REPLY — không cần trả lời",
        "(NO_REPLY)",
        # The separator is dropped in the match, so a model that omits the
        # underscore must still suppress rather than have it sent verbatim.
        "NOREPLY",
    ],
)
def test_the_sentinel_is_recognised_however_the_model_wraps_it(reply: str) -> None:
    assert manual_skip_requested(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "   ",
        "Chào anh, dự án đó vẫn đang tuyển ạ",
        "Bạn cần mình gửi link dự án không?",
        "Nói thật với anh nhé",
        "Xin chờ thêm",
    ],
)
def test_an_ordinary_reply_is_never_mistaken_for_a_skip(reply: str) -> None:
    assert manual_skip_requested(reply) is False


# --- the lane ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_agent_receives_the_review_directive_and_its_reply_is_kept() -> None:
    agent = _LaneAgent("Chào anh, phòng tuyển dụng đã ghi nhận hồ sơ của anh rồi ạ.")

    resolution = await _resolve_lane(agent)

    assert agent.kwargs["mandatory_instruction"] == MANUAL_REPLY_INSTRUCTION
    assert resolution.terminal is None
    assert resolution.candidate == agent.reply


@pytest.mark.asyncio
async def test_the_review_directive_replaces_the_project_clarification_ask() -> None:
    # A recruiter review has no candidate message to disambiguate projects
    # against, so the clarification instruction must not displace the directive
    # — otherwise the turn answers a question nobody asked.
    clarification_ctx = SimpleNamespace(
        clarification="Anh muốn tìm hiểu lương dự án nào ạ?",
        direct_context=None,
        state="EXPLORE",
        knowledge_mode="DIRECT_CONTEXT",
        clarification_projects=("Dự án A", "Dự án B"),
    )
    agent = _LaneAgent("Dạ anh cho em xin thêm thông tin nhé.")

    await _resolve_lane(agent, project_context=clarification_ctx)

    assert agent.kwargs["mandatory_instruction"] == MANUAL_REPLY_INSTRUCTION


@pytest.mark.asyncio
async def test_a_requested_silence_sends_nothing_and_is_recorded_as_a_skip() -> None:
    agent = _LaneAgent("NO_REPLY")

    resolution = await _resolve_lane(agent)

    # No candidate text reaches the dispatch tail, and the outcome names the
    # deliberate skip rather than the generic suppressed/error reasons.
    assert resolution.candidate == ""
    assert resolution.terminal == {"outcome": "manual_skip", "reply": ""}


@pytest.mark.asyncio
async def test_the_skip_records_an_unsent_empty_outcome() -> None:
    svc = _svc()

    from app.graph.lanes import _resolve_lane
    from app.graph.ports import TurnDecisions

    await _resolve_lane(
        state=_manual_state(),
        deps=_deps(),
        conv=SimpleNamespace(contact_id=None),
        svc=svc,
        decisions=TurnDecisions(intent="general", intent_confidence=0.9),
        turn_route=SimpleNamespace(intent="general", reason="empty", confidence=0.1),
        project_context=None,
        recent_messages=[],
        manifest_policy=None,
        provider="zalo_bot",
        recipient_id="u1",
        timings={},
        started="2026-10-08T00:00:00+00:00",
        lock_owner="owner-1",
        status_task=None,
        t0=0.0,
        agent_turn=_LaneAgent("NO_REPLY"),
    )

    svc.record_bot_outcome.assert_awaited_once()
    kwargs = svc.record_bot_outcome.await_args.kwargs
    assert kwargs["reply"] == ""
    assert kwargs["sent"] is False


@pytest.mark.asyncio
async def test_the_sentinel_is_only_a_skip_on_a_recruiser_review_turn() -> None:
    # On an ordinary inbound turn the lane must not reinterpret the model's
    # text: the skip contract belongs to the review turn alone.
    state = BotRunState(conversation_id=CONV_ID, version_at_start=3, user_text="chào")

    resolution = await _resolve_lane(_LaneAgent("NO_REPLY"), state=state)

    assert resolution.terminal is None
    assert resolution.candidate == "NO_REPLY"


# --- the prompt --------------------------------------------------------------


def test_the_prompt_marks_a_review_turn_as_having_no_new_message() -> None:
    history = [
        SimpleNamespace(sender="WORKER", body="Anh muốn ứng tuyển vị trí nào ạ?"),
        SimpleNamespace(sender="WORKER", body="😊"),
    ]

    prompt = build_agent_user_text(
        chat_id="u1",
        current_user_text="",
        recent_messages=history,
        route_hint=MANUAL_REPLY_INSTRUCTION,
        manual_review=True,
    )

    # The review turn must not tell the agent to answer "the current message":
    # there is none, and the history is the input.
    assert "KHÔNG CÓ TIN NHẮN MỚI" in prompt
    assert "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN" not in prompt
    assert "MANUAL_REPLY" not in prompt
    assert "Anh muốn ứng tuyển vị trí nào ạ?" in prompt
    assert MANUAL_REPLY_INSTRUCTION in prompt


def test_an_ordinary_turn_keeps_its_current_message_section() -> None:
    prompt = build_agent_user_text(
        chat_id="u1",
        current_user_text="LG Tràng Duệ còn tuyển không?",
        recent_messages=[SimpleNamespace(sender="WORKER", body="Chào bạn")],
    )

    assert "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN:\nLG Tràng Duệ còn tuyển không?" in prompt
    assert "KHÔNG CÓ TIN NHẮN MỚI" not in prompt


# --- the scheduler -----------------------------------------------------------


class _ScheduleSvc:
    def __init__(self, *, lock: uuid.UUID | None = None, enqueue_result: bool = True):
        self._lock = lock
        self.enqueue_result = enqueue_result
        self.released: list = []
        self.jobs: list[dict] = []

    async def acquire_lock(self, _conv_id, *args, **kwargs):  # noqa: ARG002
        return self._lock

    async def release_lock(self, _conv, *, lock_owner=None):
        self.released.append(lock_owner)


@pytest.mark.asyncio
async def test_the_scheduled_job_carries_no_inbound_and_flags_the_review() -> None:
    from app.services.conversation.scheduler import enqueue_manual_bot_turn

    svc = _ScheduleSvc(lock=uuid.uuid4())
    conv = SimpleNamespace(id=CONV_UUID, version=9)

    enqueued = await enqueue_manual_bot_turn(
        svc,
        conv,
        enqueue=lambda job: svc.jobs.append(job) or True,
    )

    assert enqueued is True
    (job,) = svc.jobs
    # The worker reads these two: no inbound to answer, and the flag that
    # resolves into the agent's directive.
    assert job["user_text"] == ""
    assert job["reply_to_message_id"] == ""
    assert job["manual_turn"] is True
    assert manual_instruction_for(job["manual_turn"]) == MANUAL_REPLY_INSTRUCTION
    assert job["version_at_start"] == 9
    assert job["lock_owner"] == str(svc._lock)
    assert job["received_at_epoch"] > 0


@pytest.mark.asyncio
async def test_a_held_conversation_lock_refuses_the_review_instead_of_queueing() -> None:
    from app.services.conversation.scheduler import enqueue_manual_bot_turn

    svc = _ScheduleSvc(lock=None)

    enqueued = await enqueue_manual_bot_turn(
        svc,
        SimpleNamespace(id=CONV_UUID, version=9),
        enqueue=lambda job: svc.jobs.append(job) or True,
    )

    assert enqueued is False
    assert svc.jobs == []


@pytest.mark.asyncio
async def test_a_rejected_enqueue_releases_the_conversation_lock() -> None:
    from app.services.conversation.scheduler import enqueue_manual_bot_turn

    owner = uuid.uuid4()
    svc = _ScheduleSvc(lock=owner, enqueue_result=False)

    enqueued = await enqueue_manual_bot_turn(
        svc,
        SimpleNamespace(id=CONV_UUID, version=9),
        enqueue=lambda job: svc.jobs.append(job) or None,
    )

    # A refused hand-off must not leave the chat locked for its whole TTL —
    # that would strand the candidate behind every later turn too.
    assert enqueued is False
    assert svc.released == [owner]


# --- the route ---------------------------------------------------------------


def _client(conv: SimpleNamespace) -> object:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import conversations as conversations_api
    from app.api.auth_dependencies import get_current_user
    from app.core.errors import register_domain_exception_handlers
    from app.shared.infrastructure.db import get_request_db

    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(conversations_api.router, prefix="/api/v1")
    app.dependency_overrides[get_request_db] = lambda: SimpleNamespace()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())

    async def _load(_conv_id, _db, _user):
        return conv

    conversations_api._load = _load  # type: ignore[method-assign]
    return TestClient(app)


@pytest.fixture
def bot_conv():
    from datetime import UTC, datetime

    from app.conversation_messaging.domain.statuses import (
        ConversationMode,
        ConversationStatus,
    )
    from app.models.conversation import Conversation

    conv = Conversation(
        zalo_chat_id="fb-bot-review",
        zalo_channel="facebook_messenger",
        mode=ConversationMode.BOT,
        status=ConversationStatus.OPEN,
        needs_human=False,
        unread_count=0,
        project_context_state="EXPLORE",
        version=4,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conv.id = CONV_UUID
    return conv


@pytest.fixture
def _restore_load():
    from app.api import conversations as conversations_api

    original = conversations_api._load
    yield
    conversations_api._load = original  # type: ignore[method-assign]


def _patch_route(monkeypatch, *, enqueued: bool) -> None:
    from app.api import conversations as conversations_api

    async def _enqueue(_svc, _conv, *, enqueue):
        assert callable(enqueue)
        return enqueued

    monkeypatch.setattr(conversations_api, "enqueue_manual_bot_turn", _enqueue)


def test_bot_reply_queues_a_review_even_when_nothing_is_waiting(
    monkeypatch, bot_conv
) -> None:
    _patch_route(monkeypatch, enqueued=True)

    response = _client(bot_conv).post(f"/api/v1/conversations/{CONV_UUID}/bot-reply")

    assert response.status_code == 200


def test_bot_reply_refuses_a_taken_over_thread(monkeypatch, bot_conv) -> None:
    from app.conversation_messaging.domain.statuses import ConversationMode

    _patch_route(monkeypatch, enqueued=True)
    bot_conv.mode = ConversationMode.HUMAN

    response = _client(bot_conv).post(f"/api/v1/conversations/{CONV_UUID}/bot-reply")

    assert response.status_code == 409
    assert "nhân viên" in response.json()["detail"]


def test_bot_reply_reports_a_turn_already_running(monkeypatch, bot_conv) -> None:
    _patch_route(monkeypatch, enqueued=False)

    response = _client(bot_conv).post(f"/api/v1/conversations/{CONV_UUID}/bot-reply")

    # The per-conversation lock is what refused it, so the operator is told to
    # wait rather than being told there was nothing to answer.
    assert response.status_code == 409
    assert "đang xử lý" in response.json()["detail"]