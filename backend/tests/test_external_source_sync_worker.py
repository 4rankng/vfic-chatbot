"""Hermetic tests for the external-source sync RQ worker + scheduler tick."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.knowledge.external_source_sync import ExternalSourceSyncOutcome
from app.workers import external_source_sync_worker as w

MODULE = Path(w.__file__).name


class _FakeSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_exc):
        return False


def _db_returning_state_ids(state_ids):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(state_ids)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_tick_noop_when_no_auto_sync_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tick is a no-op when no rows have auto_sync_enabled=true.

    Replaces the old test_tick_noop_when_globally_disabled — the global kill
    switch was removed; per-row auto_sync_enabled is now the sole control.
    """
    enqueued = []
    monkeypatch.setattr(w, "enqueue_one_shot", lambda *a, **k: enqueued.append(a) or "job")
    db = _db_returning_state_ids([])
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))

    await w._tick_async()
    assert enqueued == []


@pytest.mark.asyncio
async def test_tick_enqueues_one_job_per_auto_sync_row(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    enqueued = []
    monkeypatch.setattr(w, "enqueue_one_shot", lambda state_id, job_id=None: enqueued.append((str(state_id), job_id)) or f"job-{state_id}")
    db = _db_returning_state_ids(ids)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))

    await w._tick_async()
    assert len(enqueued) == 3
    # Daily-dedupe job_id shape: ext-src-sync-{state_id}-{YYYY-MM-DD}
    for state_id, job_id in enqueued:
        assert job_id.startswith(f"ext-src-sync-{state_id}-")


@pytest.mark.asyncio
async def test_run_job_async_invokes_orchestrator_and_bumps_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4(), category_key="faq")
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))
    monkeypatch.setattr(w, "_resolve_actor", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    monkeypatch.setattr(
        "app.services.knowledge.external_source_sync.sync_external_source",
        AsyncMock(
            return_value=ExternalSourceSyncOutcome(
                status="STAGED", category_key="faq", content_hash="abcd1234"
            )
        ),
    )
    counters = []
    monkeypatch.setattr(w, "_bump_counter", lambda key: counters.append(key))

    await w._run_job_async(state.id)
    assert w.COUNTER_SUCCESS in counters


def _pool_recording_session(pool: str, opened: list[str], db):
    class _RecordingSessionCM:
        async def __aenter__(self):
            opened.append(pool)
            return db

        async def __aexit__(self, *_exc):
            return False

    return _RecordingSessionCM()


@pytest.mark.asyncio
async def test_worker_tick_uses_worker_pool_never_the_web_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 21: the tick must run on worker_session, never the web pool's
    async_session — the web pool is sized for request latency and saturates when
    a full auto-sync backlog drains through it.

    This used to read the worker module's source and grep it for the import,
    which passes while the worker actually opens the web pool and fails on any
    reformat of the import block. It now installs a tripwire on both session
    factories and asserts which one the real code path entered.
    """
    opened: list[str] = []
    db = _db_returning_state_ids([])
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _pool_recording_session("worker", opened, db))
    monkeypatch.setattr("app.core.db.async_session", lambda: _pool_recording_session("web", opened, db))
    monkeypatch.setattr(w, "enqueue_one_shot", lambda *a, **k: "job-id")

    await w._tick_async()

    assert opened == ["worker"], f"the sync tick opened the {opened} pool"


@pytest.mark.asyncio
async def test_worker_job_uses_worker_pool_never_the_web_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-row RQ job shares the tick's pool contract (Finding 21)."""
    opened: list[str] = []
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4(), category_key="faq"))
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _pool_recording_session("worker", opened, db))
    monkeypatch.setattr("app.core.db.async_session", lambda: _pool_recording_session("web", opened, db))
    monkeypatch.setattr(w, "_resolve_actor", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    monkeypatch.setattr(
        "app.services.knowledge.external_source_sync.sync_external_source",
        AsyncMock(
            return_value=ExternalSourceSyncOutcome(
                status="STAGED", category_key="faq", content_hash="abcd1234"
            )
        ),
    )

    await w._run_job_async(uuid.uuid4())

    assert opened == ["worker"], f"the sync job opened the {opened} pool"


@pytest.mark.asyncio
async def test_resolve_actor_prefers_created_by_then_admin() -> None:
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin")
    other_admin = SimpleNamespace(id=uuid.uuid4(), role="admin")
    db = AsyncMock()
    # First get() = created_by user; never reaches the admin fallback.
    db.get = AsyncMock(return_value=admin)
    db.scalar = AsyncMock(return_value=other_admin)
    state = SimpleNamespace(created_by=admin.id)
    actor = await w._resolve_actor(db, state)
    assert actor is admin


@pytest.mark.asyncio
async def test_resolve_actor_falls_back_to_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin")
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)  # created_by missing
    db.scalar = AsyncMock(return_value=admin)
    state = SimpleNamespace(created_by=uuid.uuid4())
    actor = await w._resolve_actor(db, state)
    assert actor is admin
