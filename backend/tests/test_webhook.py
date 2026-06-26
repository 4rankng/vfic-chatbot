"""US-006 webhook tests: the synchronous guard chain must ack fast (<1s) and
correctly dedup / starve-in-human-mode / respect the per-chat lock."""
import time

import pytest
from sqlalchemy import text

from app.services.webhook import ZaloWebhookService

pytestmark = pytest.mark.asyncio


def _payload(msg_id, text="hi", chat_id="z-1", name="Worker"):
    # Bot Platform receive-event shape (Telegram-style).
    return {
        "update_id": msg_id,
        "message": {
            "message_id": msg_id,
            "date": 1700000000,
            "chat": {"id": chat_id},
            "from": {"id": chat_id, "name": name},
            "text": text,
        },
    }


async def _enqueue(captured):
    async def fn(job):
        captured.append(job)

    return fn


async def test_webhook_queues_then_dedups_and_acks_fast(db_session):
    captured = []
    eq = await _enqueue(captured)

    t0 = time.monotonic()
    r1 = await ZaloWebhookService.handle(db_session, _payload("m1", chat_id="z-1"), enqueue=eq)
    elapsed = time.monotonic() - t0
    assert r1["status"] == "queued"
    assert len(captured) == 1
    assert elapsed < 1.5, f"webhook ack took {elapsed:.2f}s"

    # same msg_id within the 8s window -> duplicate, not re-enqueued
    r2 = await ZaloWebhookService.handle(db_session, _payload("m1", chat_id="z-1"), enqueue=eq)
    assert r2["status"] == "duplicate"
    assert len(captured) == 1


async def test_webhook_starves_in_human_mode(db_session):
    captured = []
    eq = await _enqueue(captured)
    await ZaloWebhookService.handle(db_session, _payload("m2", chat_id="z-2"), enqueue=eq)
    await db_session.execute(
        text("UPDATE conversations SET mode='HUMAN', version=version+1 WHERE zalo_chat_id='z-2'")
    )
    await db_session.commit()

    n_before = len(captured)
    r = await ZaloWebhookService.handle(db_session, _payload("m3", chat_id="z-2"), enqueue=eq)
    assert r["status"] == "starved_human_mode"
    assert len(captured) == n_before  # the HUMAN-mode inbound did NOT enqueue a bot run


async def test_webhook_locked_when_mutex_held(db_session):
    captured = []
    eq = await _enqueue(captured)
    # first message acquires the 30s lock
    await ZaloWebhookService.handle(db_session, _payload("m4", chat_id="z-3"), enqueue=eq)
    # a second message while the lock is held -> locked, not re-enqueued
    r = await ZaloWebhookService.handle(db_session, _payload("m5", chat_id="z-3"), enqueue=eq)
    assert r["status"] == "locked"
    assert len(captured) == 1


async def test_webhook_ignores_non_text_events(db_session):
    captured = []
    eq = await _enqueue(captured)
    r = await ZaloWebhookService.handle(
        db_session, {"event_name": "follow", "sender": {"id": "x"}}, enqueue=eq
    )
    assert r["status"] == "ignored"
    assert captured == []


async def test_webhook_http_endpoint(client, monkeypatch):
    import app.api.webhooks as wh

    called = []
    monkeypatch.setattr(wh, "enqueue_chat_run", lambda job: called.append(job))
    r = await client.post("/webhooks/zalo", json=_payload("h1", chat_id="z-http"))
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert len(called) == 1


async def test_webhook_rejects_unsigned_when_secret_set(client, monkeypatch):
    """With zalo_bot_webhook_secret configured, only a request bearing the correct
    X-Bot-Api-Secret-Token header is accepted."""
    from app.core.config import get_settings
    import app.api.webhooks as wh

    monkeypatch.setattr(get_settings(), "zalo_bot_webhook_secret", "test-secret")
    monkeypatch.setattr(wh, "enqueue_chat_run", lambda job: None)

    body = _payload("sig-1", chat_id="z-sig")
    ct = {"Content-Type": "application/json"}

    unsigned = await client.post("/webhooks/zalo", json=body, headers=ct)
    assert unsigned.status_code == 401

    wrong = await client.post(
        "/webhooks/zalo", json=body, headers={**ct, "X-Bot-Api-Secret-Token": "wrong-value"}
    )
    assert wrong.status_code == 401

    ok = await client.post(
        "/webhooks/zalo", json=body, headers={**ct, "X-Bot-Api-Secret-Token": "test-secret"}
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "queued"


async def test_webhook_accepts_unsigned_when_no_secret(client, monkeypatch):
    """With no secret configured (dev/test), verification is skipped."""
    import app.api.webhooks as wh

    monkeypatch.setattr(wh, "enqueue_chat_run", lambda job: None)
    r = await client.post("/webhooks/zalo", json=_payload("sig-2", chat_id="z-sig2"))
    assert r.status_code == 200


async def test_webhook_rejects_unsigned_in_nondev_without_secret(client, monkeypatch):
    """Non-dev with NO webhook secret configured must fail-closed (503), not accept
    blind — otherwise anyone could inject inbound messages."""
    import app.api.webhooks as wh
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    monkeypatch.setattr(s, "zalo_bot_webhook_secret", "")
    monkeypatch.setattr(wh, "enqueue_chat_run", lambda job: None)
    r = await client.post("/webhooks/zalo", json=_payload("sig-3", chat_id="z-sig3"))
    assert r.status_code == 503

