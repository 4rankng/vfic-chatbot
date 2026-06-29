"""US-005 tests: ConversationService + recruiter reply + SSE realtime.

Covers acceptance #1 (takeover race), #2 (human-mode inbound starves bot),
#3 (recruiter reply + non-owner 409), plus take_over/release/close/mark_read/
last_messages and the SSE stream.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.services.conversation import ConversationService
from app.services.zalo_bot_service import SendResult, ZaloBotSender
from tests.conftest import ADMIN_EMAIL, PASSWORD, RECRUITER_EMAIL

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mock_zalo(monkeypatch):
    async def fake_send(self, zalo_chat_id, text):
        return SendResult(ok=True, msg_id="zalo-mock-1")

    monkeypatch.setattr(ZaloBotSender, "send", fake_send)


def _bearer(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


async def _admin_token(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _recruiter_token(client) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"email": RECRUITER_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _make_conv(db_session, zalo="c-1") -> Conversation:
    conv = Conversation(zalo_chat_id=zalo)
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)
    return conv


# --- acceptance #1: takeover race ------------------------------------------------


async def test_takeover_race_suppresses_bot(client, db_session):
    rec_tok = await _recruiter_token(client)
    h = {"Authorization": f"Bearer {rec_tok}"}

    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, "race-1")
    version_at_start = conv.version  # 1

    # recruiter takes over AFTER the bot run already started (captured version_at_start)
    r = await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "HUMAN"

    await db_session.refresh(conv)
    assert conv.version == version_at_start + 1
    # pre-send guard: bot started at v1, conversation is now v2/HUMAN -> must NOT send
    assert await svc.recheck_ownership(conv, version_at_start) is False

    started = datetime.now(timezone.utc) - timedelta(seconds=2)
    await svc.record_bot_outcome(
        conv,
        version_at_start=version_at_start,
        reply="bot intended reply",
        started_at=started,
        sent=False,
    )

    runs = (await db_session.scalars(select(BotRun).where(BotRun.conversation_id == conv.id))).all()
    assert len(runs) == 1
    assert runs[0].outcome == BotRunOutcome.SUPPRESSED
    assert runs[0].version_at_start == version_at_start
    bot_msgs = (
        await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.sender == MessageSender.BOT
            )
        )
    ).all()
    assert len(bot_msgs) == 1 and bot_msgs[0].delivery_status == DeliveryStatus.SUPPRESSED


# --- acceptance #2: human-mode inbound starves the bot --------------------------


async def test_human_mode_inbound_starves_bot(client, db_session):
    rec_tok = await _recruiter_token(client)
    h = {"Authorization": f"Bearer {rec_tok}"}
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, "human-1")

    # take over -> HUMAN
    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=h)
    ).status_code == 200
    await db_session.refresh(conv)
    assert conv.mode == ConversationMode.HUMAN

    # run_start_guard must starve (bot does NOT run in HUMAN mode)
    assert svc.run_start_guard(conv) is False

    before = conv.unread_count
    await svc.record_inbound(conv, body="Ứng viên trả lời", zalo_message_id="zin-1")
    await db_session.refresh(conv)
    assert conv.unread_count == before + 1  # recruiter sees unread bump
    inbound_msgs = (
        await db_session.scalars(
            select(Message).where(
                Message.conversation_id == conv.id, Message.sender == MessageSender.WORKER
            )
        )
    ).all()
    assert [m.body for m in inbound_msgs] == ["Ứng viên trả lời"]

    # no bot_run was created for this inbound
    runs = (await db_session.scalars(select(BotRun).where(BotRun.conversation_id == conv.id))).all()
    assert runs == []


# --- acceptance #3: recruiter reply (200) + non-owner/untaken 409 ----------------


async def test_recruiter_reply_flow(client, db_session):
    admin_tok = await _admin_token(client)
    admin_h = {"Authorization": f"Bearer {admin_tok}"}
    rec_tok = await _recruiter_token(client)
    rec_h = {"Authorization": f"Bearer {rec_tok}"}

    conv = await _make_conv(db_session, "reply-1")

    # reply before takeover (mode=BOT) -> 409
    r0 = await client.post(
        f"/api/v1/conversations/{conv.id}/messages", json={"body": "hi"}, headers=rec_h
    )
    assert r0.status_code == 409

    # recruiter takes over, then replies -> 201
    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=rec_h)
    ).status_code == 200
    r1 = await client.post(
        f"/api/v1/conversations/{conv.id}/messages", json={"body": "Chào bạn"}, headers=rec_h
    )
    assert r1.status_code == 201, r1.text
    body = r1.json()
    assert body["sender"] == "RECRUITER"
    assert body["delivery_status"] == "SENT"
    assert body["zalo_message_id"] == "zalo-mock-1"

    # a different recruiter must be rejected with 409
    other_email = f"other.{asyncio.get_running_loop().time():.0f}@example.com"
    created = await client.post(
        "/api/v1/users",
        json={"email": other_email, "password": "Abcd1234!", "role": "recruiter"},
        headers=admin_h,
    )
    assert created.status_code == 201
    other_login = await client.post(
        "/api/v1/auth/login", json={"email": other_email, "password": "Abcd1234!"}
    )
    other_h = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    r2 = await client.post(
        f"/api/v1/conversations/{conv.id}/messages",
        json={"body": "xin chen ngang"},
        headers=other_h,
    )
    assert r2.status_code == 409


async def test_semi_auto_mode_allows_recruiter_reply(client, db_session):
    rec_tok = await _recruiter_token(client)
    rec_h = {"Authorization": f"Bearer {rec_tok}"}
    conv = await _make_conv(db_session, "semi-api-1")

    mode = await client.post(f"/api/v1/conversations/{conv.id}/semi-auto", headers=rec_h)
    assert mode.status_code == 200, mode.text
    assert mode.json()["mode"] == "SEMI_AUTO"

    reply = await client.post(
        f"/api/v1/conversations/{conv.id}/messages",
        json={"body": "Mình đang xem hồ sơ của bạn"},
        headers=rec_h,
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["sender"] == "RECRUITER"


async def test_recruiter_reply_failed_delivery_returns_502(client, db_session, monkeypatch):
    """A failed Zalo delivery still records the FAILED message but returns 5xx."""
    from app.services.zalo_bot_service import SendResult, ZaloBotSender

    async def fail_send(self, zalo_chat_id, text):
        return SendResult(ok=False, error="upstream zalo timeout")

    # override the autouse _mock_zalo ok-send with a failing one for this test
    monkeypatch.setattr(ZaloBotSender, "send", fail_send)

    rec_tok = await _recruiter_token(client)
    rec_h = {"Authorization": f"Bearer {rec_tok}"}
    conv = await _make_conv(db_session, "fail-1")
    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=rec_h)
    ).status_code == 200

    r = await client.post(
        f"/api/v1/conversations/{conv.id}/messages", json={"body": "hello"}, headers=rec_h
    )
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["delivery_status"] == "FAILED"
    assert body["external_error"] == "upstream zalo timeout"
    await db_session.refresh(conv)
    assert conv.last_outbound_at is None


# --- take-over conflict between recruiters --------------------------------------


async def test_takeover_conflict(client, db_session):
    admin_tok = await _admin_token(client)
    admin_h = {"Authorization": f"Bearer {admin_tok}"}
    rec1_tok = await _recruiter_token(client)
    rec1_h = {"Authorization": f"Bearer {rec1_tok}"}
    conv = await _make_conv(db_session, "conflict-1")

    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=rec1_h)
    ).status_code == 200

    # second recruiter tries the same conversation -> 409
    other_email = f"r2.{asyncio.get_running_loop().time():.0f}@example.com"
    await client.post(
        "/api/v1/users",
        json={"email": other_email, "password": "Abcd1234!", "role": "recruiter"},
        headers=admin_h,
    )
    other_tok = (
        await client.post(
            "/api/v1/auth/login", json={"email": other_email, "password": "Abcd1234!"}
        )
    ).json()["access_token"]
    conflict = await client.post(
        f"/api/v1/conversations/{conv.id}/take-over",
        headers={"Authorization": f"Bearer {other_tok}"},
    )
    assert conflict.status_code == 409


# --- mark_read / last_messages / release ---------------------------------------


async def test_mark_read_and_release(client, db_session):
    rec_tok = await _recruiter_token(client)
    h = {"Authorization": f"Bearer {rec_tok}"}
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, "read-1")
    # seed some unread + a couple messages
    conv.unread_count = 3
    db_session.add_all(
        [
            Message(conversation_id=conv.id, sender=MessageSender.WORKER, body="a"),
            Message(conversation_id=conv.id, sender=MessageSender.BOT, body="b"),
        ]
    )
    await db_session.commit()
    await db_session.refresh(conv)

    msgs = await svc.last_messages(conv, limit=10)
    assert [m.body for m in msgs] == ["a", "b"]

    marked = await client.post(f"/api/v1/conversations/{conv.id}/read", headers=h)
    assert marked.status_code == 200 and marked.json()["unread_count"] == 0

    released = await client.post(f"/api/v1/conversations/{conv.id}/release", headers=h)
    assert released.status_code == 200 and released.json()["mode"] == "BOT"


async def test_needs_attention_only_counts_unanswered_inbound(client, db_session):
    """Manual/unread chats are not enough for "Cần xử lý"; the latest user
    message must be newer than the latest successful outbound reply."""
    base = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Conversation(
                zalo_chat_id="manual-answered",
                mode=ConversationMode.HUMAN,
                unread_count=5,
                last_inbound_at=base - timedelta(minutes=2),
                last_outbound_at=base - timedelta(minutes=1),
            ),
            Conversation(
                zalo_chat_id="unanswered-after-reply",
                mode=ConversationMode.BOT,
                unread_count=0,
                last_inbound_at=base,
                last_outbound_at=base - timedelta(minutes=1),
            ),
            Conversation(
                zalo_chat_id="unanswered-no-reply",
                mode=ConversationMode.HUMAN,
                unread_count=0,
                last_inbound_at=base,
                last_outbound_at=None,
            ),
            Conversation(
                zalo_chat_id="manual-no-inbound",
                mode=ConversationMode.HUMAN,
                unread_count=10,
                last_inbound_at=None,
                last_outbound_at=None,
            ),
        ]
    )
    await db_session.commit()

    tok = await _admin_token(client)
    headers = {"Authorization": f"Bearer {tok}"}
    count = await client.get("/api/v1/conversations/needs-attention", headers=headers)
    assert count.status_code == 200, count.text
    assert count.json()["count"] == 1

    listed = await client.get(
        "/api/v1/conversations?needs_attention=true&per_page=20",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert {row["zalo_chat_id"] for row in listed.json()["data"]} == {
        "unanswered-no-reply",
    }


async def test_release_to_bot_enqueues_unanswered_worker_message(client, db_session, monkeypatch):
    import app.api.conversations as conversations_api

    captured = []
    monkeypatch.setattr(conversations_api, "enqueue_chat_run", lambda job: captured.append(job))

    rec_tok = await _recruiter_token(client)
    h = {"Authorization": f"Bearer {rec_tok}"}
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, "release-unanswered-1")

    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=h)
    ).status_code == 200
    await db_session.refresh(conv)
    await svc.record_inbound(conv, body="Cho em hỏi ca đêm còn tuyển không?", zalo_message_id="zu-1")
    await db_session.refresh(conv)

    released = await client.post(f"/api/v1/conversations/{conv.id}/release", headers=h)
    assert released.status_code == 200, released.text
    assert released.json()["mode"] == "BOT"

    assert len(captured) == 1
    assert captured[0]["conversation_id"] == str(conv.id)
    assert captured[0]["user_text"] == "Cho em hỏi ca đêm còn tuyển không?"
    assert captured[0]["version_at_start"] == released.json()["version"]


async def test_release_to_bot_does_not_enqueue_when_recruiter_answered(
    client, db_session, monkeypatch
):
    import app.api.conversations as conversations_api

    captured = []
    monkeypatch.setattr(conversations_api, "enqueue_chat_run", lambda job: captured.append(job))

    rec_tok = await _recruiter_token(client)
    h = {"Authorization": f"Bearer {rec_tok}"}
    svc = ConversationService(db_session)
    conv = await _make_conv(db_session, "release-answered-1")

    assert (
        await client.post(f"/api/v1/conversations/{conv.id}/take-over", headers=h)
    ).status_code == 200
    await db_session.refresh(conv)
    await svc.record_inbound(conv, body="Em muốn ứng tuyển", zalo_message_id="za-1")

    reply = await client.post(
        f"/api/v1/conversations/{conv.id}/messages",
        json={"body": "VFIC đã nhận thông tin, mình hỗ trợ ngay nhé."},
        headers=h,
    )
    assert reply.status_code == 201, reply.text

    released = await client.post(f"/api/v1/conversations/{conv.id}/release", headers=h)
    assert released.status_code == 200, released.text
    assert captured == []


async def test_last_messages_batch_returns_latest_per_conversation(client, db_session):
    """GET /conversations/last-messages/batch returns the latest body per
    conversation in ONE request (replaces the client-side N-fanout)."""
    conv_a = await _make_conv(db_session, "batch-a")
    conv_b = await _make_conv(db_session, "batch-b")
    # two messages on a (second has the higher id -> latest); one on b.
    db_session.add_all(
        [
            Message(conversation_id=conv_a.id, sender=MessageSender.BOT, body="old a"),
            Message(conversation_id=conv_a.id, sender=MessageSender.BOT, body="new a"),
            Message(conversation_id=conv_b.id, sender=MessageSender.BOT, body="only b"),
        ]
    )
    await db_session.commit()

    tok = await _admin_token(client)
    ids = f"{conv_a.id},{conv_b.id}"
    r = await client.get(
        f"/api/v1/conversations/last-messages/batch?ids={ids}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    snippets = r.json()["snippets"]
    assert snippets[str(conv_a.id)] == "new a"
    assert snippets[str(conv_b.id)] == "only b"


async def test_last_messages_batch_ignores_garbage_ids(client, db_session):
    conv = await _make_conv(db_session, "batch-g")
    db_session.add(Message(conversation_id=conv.id, sender=MessageSender.BOT, body="hi"))
    await db_session.commit()
    tok = await _admin_token(client)
    r = await client.get(
        "/api/v1/conversations/last-messages/batch?ids=not-a-uuid,," + f"{conv.id}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["snippets"] == {str(conv.id): "hi"}


# --- SSE realtime ---------------------------------------------------------------


async def test_realtime_pipeline_pushes_conversation_updated(client, db_session, _reset_redis):
    """A real state change (take-over) publishes conversation.updated through Redis
    pub/sub, which the SSE endpoint (app/api/realtime.py) subscribes to. We verify
    the pipeline deterministically by subscribing directly; the HTTP SSE wrapper is
    a thin auth+format layer (auth covered by test_sse_requires_token)."""
    import json as _json

    from app.core.redis import get_redis
    from app.services.realtime import CHANNEL

    rec_tok = await _recruiter_token(client)
    conv = await _make_conv(db_session, "rt-1")

    pubsub = get_redis().pubsub()
    await pubsub.subscribe(CHANNEL)
    await asyncio.sleep(0.2)  # let the subscription register server-side

    assert (
        await client.post(
            f"/api/v1/conversations/{conv.id}/take-over",
            headers={"Authorization": f"Bearer {rec_tok}"},
        )
    ).status_code == 200

    seen = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if msg and msg.get("type") == "message":
            data = _json.loads(msg["data"])
            if data.get("type") == "conversation.updated":
                seen = data
                break
    try:
        await pubsub.aclose()
    except Exception:
        pass
    assert seen is not None, "conversation.updated not delivered via Redis pub/sub"
    assert seen["payload"]["zalo_chat_id"] == "rt-1"
    assert seen["payload"]["mode"] == "HUMAN"


async def test_sse_requires_token(client):
    r = await client.get("/realtime/events")
    assert r.status_code == 401
