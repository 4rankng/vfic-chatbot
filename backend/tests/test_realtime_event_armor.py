"""Realtime seam armor: eager-load failures and swallowed errors become visible.

Two regression classes (2026-10-14 review):

1. ``conversation.updated`` died on conversations whose contact relationships
   were not loaded — MissingGreenlet swallowed to a WARNING, recruiter UI
   silently stale. The bus must armor serialization end-to-end: eager-load,
   then never raise, and count the degradation.
2. Nothing alerted on any of those WARNING catches. Every armor path now
   increments a Redis counter exported on ``/metrics``
   (``app.core.incidents``), so a silent degradation is pollable.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.conversation import events as events_mod
from app.services.conversation.events import ConversationEventBus
from app.services.realtime import publish_event


@pytest.fixture
def incidents(monkeypatch):
    """Capture counter increments instead of touching Redis."""
    counted: list[str] = []
    import app.services.conversation.bot_path as bot_path_mod
    import app.services.realtime as realtime_mod
    from app.workers import knowledge_recovery_worker

    for mod in (
        events_mod,
        realtime_mod,
        bot_path_mod,
        knowledge_recovery_worker,
    ):
        monkeypatch.setattr(
            f"{mod.__name__}.count_incident", lambda key, _c=counted: _c.append(key)
        )
    return counted


def _unserializable_conv():
    # A plain namespace is not a SQLAlchemy instance (sa_inspect returns None,
    # so the eager load no-ops) and fails ConversationOut validation — exactly
    # the armor-only path.
    return SimpleNamespace(id="conv-x")


@pytest.mark.asyncio
async def test_conversation_updated_never_raises_on_payload_failure(monkeypatch, incidents):
    published = []

    async def fake_publish(event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(events_mod, "publish_event", fake_publish)
    bus = ConversationEventBus(db=object())

    # Before the armor this raised pydantic ValidationError up the stack.
    await bus.conversation_updated(_unserializable_conv())

    assert published == []
    assert incidents == ["realtime_payload_failures_total"]


@pytest.mark.asyncio
async def test_conversation_updated_publishes_loaded_conversation(monkeypatch, incidents):
    published = []

    async def fake_publish(event_type, payload):
        published.append((event_type, payload))

    monkeypatch.setattr(events_mod, "publish_event", fake_publish)
    monkeypatch.setattr(events_mod, "_conv_payload", lambda conv: {"id": str(conv.id)})
    bus = ConversationEventBus(db=object())

    await bus.conversation_updated(SimpleNamespace(id="conv-ok"))

    assert published == [("conversation.updated", {"id": "conv-ok"})]
    assert incidents == []


@pytest.mark.asyncio
async def test_schedule_realtime_armor_counts_payload_failure(monkeypatch, incidents):
    """The sync schedule path cannot eager-load; its serialization armor must
    at least count the skip (2026-10-13/14 prod: silently lost events)."""

    def _boom(conv):
        raise ValueError("unloaded relationship")

    monkeypatch.setattr(events_mod, "_conv_payload", _boom)
    monkeypatch.setattr(events_mod, "_message_payload", lambda msg: {"ok": True})
    bus = ConversationEventBus(db=object())

    bus.schedule_realtime(SimpleNamespace(id=1), SimpleNamespace(id="conv-x"))

    # Give the created task a chance to run (there is nothing to publish —
    # serialization failed before task creation).
    for task in list(events_mod._background_tasks):
        task.cancel()
    assert incidents == ["realtime_payload_failures_total"]


@pytest.mark.asyncio
async def test_publish_event_swallows_and_counts_socket_io_failure(monkeypatch, incidents):
    async def exploding_emit(*_args, **_kwargs):
        raise RuntimeError("socket.io bus down")

    import app.realtime.emitter as emitter_mod
    import app.realtime.socketio as socketio_mod

    monkeypatch.setattr(emitter_mod, "emit_event", exploding_emit)
    monkeypatch.setattr(socketio_mod, "_room_for_payload", lambda _p: "room-1")

    # Must not raise; the failure is counted instead of only logged.
    await publish_event("conversation.updated", {"conversation_id": "c"})

    assert incidents == ["realtime_publish_failures_total"]


@pytest.mark.asyncio
async def test_metrics_exports_incident_counters(monkeypatch):
    """/metrics must surface the incident keys — this is the entire point of
    the counters (ops-alerts.sh polls them; nothing else would see a rise)."""
    from app.core import redis as redis_mod
    from app.main import metrics as metrics_endpoint

    class FakeQueue:
        def __init__(self, _name, connection=None):
            pass

        @property
        def count(self):
            return 0

    class FakeWorker:
        @staticmethod
        def count(connection=None):
            return 0

    class FakeRedis:
        @staticmethod
        def get(key):
            return b"3" if key in (
                "realtime_payload_failures_total",
                "realtime_publish_failures_total",
                "knowledge_recovery_failures_total",
            ) else b"0"

    import rq

    monkeypatch.setattr(redis_mod, "get_redis_sync", lambda: FakeRedis())
    monkeypatch.setattr(rq, "Queue", FakeQueue)
    monkeypatch.setattr(rq, "Worker", FakeWorker)
    payload = await metrics_endpoint()
    assert payload["realtime_payload_failures_total"] == 3
    assert payload["realtime_publish_failures_total"] == 3
    assert payload["knowledge_recovery_failures_total"] == 3
    assert payload["reconcile_re_enqueues_total"] == 0


def test_knowledge_recovery_tick_counts_and_reraises(monkeypatch):
    """The tick's counter increment must not swallow the RQ job failure — the
    failed job is still the loud signal; the counter makes the trend pollable."""
    from app.workers import knowledge_recovery_worker as worker

    counted: list[str] = []
    monkeypatch.setattr(
        "app.workers.knowledge_recovery_worker.count_incident",
        lambda key: counted.append(key),
    )

    class FakeConn:
        def set(self, *_a, **_k):
            return True

        def get(self, *_a):
            return "owner"

        def delete(self, *_a):
            return None

    async def exploding_sweep(_db):
        raise AttributeError("'coroutine' object has no attribute 'all'")

    class ExplodingSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr("app.core.redis.get_redis_sync", lambda: FakeConn())
    monkeypatch.setattr(
        "app.services.knowledge.recovery_sweep.recover_abandoned_ingest_work",
        exploding_sweep,
    )
    monkeypatch.setattr(
        "app.workers._db.worker_session", lambda: ExplodingSession(), raising=False
    )

    with pytest.raises(AttributeError):
        worker.run_knowledge_recovery_tick()

    assert counted == ["knowledge_recovery_failures_total"]


def test_count_incident_never_raises(monkeypatch):
    from app.core import incidents as incidents_mod

    def exploding_conn():
        raise RuntimeError("redis gone")

    monkeypatch.setattr("app.core.redis.get_redis_sync", exploding_conn)
    incidents_mod.count_incident("realtime_payload_failures_total")  # must not raise


def test_purge_wiring_present_in_lifespan_registration():
    """main.py must call the purge on boot, or the Redis cleanup is a one-off
    manual fix that regresses on the next removed feature."""
    import inspect

    from app.main import lifespan

    src = inspect.getsource(lifespan)
    assert "purge_dead_ticks(" in src


def test_all_counters_match_metrics_polling(tmp_path):
    """ops-alerts.sh polls key names in shell; a typo there silently drops the
    alert. Keep the script's list in lockstep with the exported counters."""
    from pathlib import Path

    from app.core.incidents import ALL_COUNTERS

    script = Path(__file__).resolve().parents[2] / "scripts" / "ops-alerts.sh"
    text = script.read_text(encoding="utf-8")
    for key in ALL_COUNTERS:
        assert key in text, f"ops-alerts.sh no longer polls {key}"
