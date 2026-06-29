"""US-006 graph runner tests with a MOCKED LLM: clean-reply send, takeover
suppression, and off-topic refusal via the safety->retry path. (Acceptance #4/#5
live parity is exercised through graph/factories.py + clients.py with real MiniMax keys.)"""

import asyncio

import pytest
from sqlalchemy import select, text

import app.graph.runner as runner
from app.graph.runner import BotRunState, GraphDeps, _build_agent_user_text, run_turn
from app.models.conversation import BotRun, BotRunOutcome, Conversation
from app.services.zalo_bot_service import SendResult

pytestmark = pytest.mark.asyncio


class FakeAgent:
    def __init__(self, replies):
        self.replies = replies
        self.calls = 0

    async def agent(self, user_text, *, system, db, embedder):
        r = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return r


class FakeSafety:
    def __init__(self, verdict_json):
        self.verdict = verdict_json

    async def safety(self, candidate):
        return self.verdict


class FakeZalo:
    def __init__(self):
        self.sends = []
        self.typing_chat_ids = []

    async def send(self, chat_id, body):
        self.sends.append(body)
        return SendResult(ok=True, msg_id="z-mock")

    async def typing(self, chat_id):
        self.typing_chat_ids.append(chat_id)


class SlowAgent(FakeAgent):
    async def agent(self, user_text, *, system, db, embedder):
        await asyncio.sleep(0.035)
        return await super().agent(user_text, system=system, db=db, embedder=embedder)


async def _make_conv(db, zalo="bot-1") -> Conversation:
    conv = Conversation(zalo_chat_id=zalo)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def test_runner_sends_clean_reply(db_session):
    conv = await _make_conv(db_session)
    deps = GraphDeps(
        db=db_session,
        agent=FakeAgent(["Bạn đang muốn tìm việc ở khu vực nào?"], ),
        safety=FakeSafety(""),
        embedder=None,
        zalo=FakeZalo(),
    )
    out = await run_turn(
        BotRunState(conversation_id=str(conv.id), version_at_start=conv.version, user_text="tìm việc"),
        deps,
    )
    assert out["outcome"] == "sent"
    assert len(deps.zalo.sends) == 1
    run = (await db_session.scalars(select(BotRun).where(BotRun.conversation_id == conv.id))).first()
    assert run.outcome == BotRunOutcome.SENT


async def test_runner_refreshes_zalo_typing_while_processing(db_session, monkeypatch):
    monkeypatch.setattr(runner, "ZALO_TYPING_HEARTBEAT_SECONDS", 0.01)
    conv = await _make_conv(db_session, "bot-typing")
    deps = GraphDeps(
        db=db_session,
        agent=SlowAgent(["Bạn đang muốn tìm việc ở khu vực nào?"]),
        safety=FakeSafety(""),
        embedder=None,
        zalo=FakeZalo(),
    )

    out = await run_turn(
        BotRunState(conversation_id=str(conv.id), version_at_start=conv.version, user_text="tìm việc"),
        deps,
    )

    assert out["outcome"] == "sent"
    assert deps.zalo.sends == ["Bạn đang muốn tìm việc ở khu vực nào?"]
    assert len(deps.zalo.typing_chat_ids) >= 2
    assert set(deps.zalo.typing_chat_ids) == {"bot-typing"}


async def test_runner_suppresses_after_takeover(db_session):
    conv = await _make_conv(db_session, "bot-2")
    conv_id = str(conv.id)
    v0 = conv.version
    # recruiter took over mid-generation: mode HUMAN + version bump
    await db_session.execute(
        text("UPDATE conversations SET mode='HUMAN', version=version+1 WHERE id=:i"), {"i": conv_id}
    )
    await db_session.commit()
    db_session.expire_all()  # raw UPDATE bypassed the ORM -> drop the stale cached row

    deps = GraphDeps(
        db=db_session,
        agent=FakeAgent(["câu trả lời sạch"]),
        safety=FakeSafety(""),
        embedder=None,
        zalo=FakeZalo(),
    )
    out = await run_turn(
        BotRunState(conversation_id=conv_id, version_at_start=v0, user_text="hi"), deps
    )
    assert out["outcome"] == "suppressed"
    assert deps.zalo.sends == []  # pre_send_guard blocked the send
    run = (await db_session.scalars(select(BotRun))).first()
    assert run.outcome == BotRunOutcome.SUPPRESSED


async def test_runner_off_topic_refusal_via_retry(db_session):
    conv = await _make_conv(db_session, "bot-3")
    refusal = (
        "Tôi là trợ lý tìm việc của VFIC nên chỉ có thể hỗ trợ bạn các vấn đề liên quan đến "
        "tuyển dụng. Bạn đang muốn tìm việc ở khu vực nào nhỉ?"
    )
    deps = GraphDeps(
        db=db_session,
        agent=FakeAgent(["đây là code python ```print(1)```", refusal]),
        safety=FakeSafety(
            '{"safe_to_send":false,"issue_found":true,"issue_type":"code_detected","final_answer":""}'
        ),
        embedder=None,
        zalo=FakeZalo(),
    )
    out = await run_turn(
        BotRunState(conversation_id=str(conv.id), version_at_start=conv.version, user_text="viết code python"),
        deps,
    )
    assert out["outcome"] == "sent"
    assert "tuyển dụng" in out["reply"]
    assert len(deps.zalo.sends) == 1
    # safety WAS consulted (the off-topic candidate was caught)
    assert deps.agent.calls == 2  # initial + retry


# --- _build_agent_user_text with lead_profile ---


def test_build_agent_user_text_no_profile_no_section():
    out = _build_agent_user_text(
        chat_id="z-1",
        current_user_text="tìm việc",
        recent_messages=[],
    )
    assert "THÔNG TIN ỨNG VIÊN" not in out
    assert "LỊCH SỬ GẦN ĐÂY" in out


def test_build_agent_user_text_with_profile_shows_section():
    profile = "THÔNG TIN ỨNG VIÊN:\n- Tên: chưa có\n- Số điện thoại: chưa có"
    out = _build_agent_user_text(
        chat_id="z-1",
        current_user_text="tìm việc",
        recent_messages=[],
        lead_profile=profile,
    )
    assert "THÔNG TIN ỨNG VIÊN" in out
    # Profile appears before history
    profile_pos = out.index("THÔNG TIN ỨNG VIÊN")
    history_pos = out.index("LỊCH SỬ GẦN ĐÂY")
    assert profile_pos < history_pos


def test_build_agent_user_text_empty_profile_omits_section():
    out = _build_agent_user_text(
        chat_id="z-1",
        current_user_text="tìm việc",
        recent_messages=[],
        lead_profile="",
    )
    assert "THÔNG TIN ỨNG VIÊN" not in out
