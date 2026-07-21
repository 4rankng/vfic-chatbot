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
async def test_tick_noop_when_globally_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(external_source_sync_enabled=False),
    )
    enqueued = []
    monkeypatch.setattr(w, "enqueue_one_shot", lambda *a, **k: enqueued.append(a) or "job")
    db = _db_returning_state_ids([uuid.uuid4()])
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))

    await w._tick_async()
    assert enqueued == []  # never queried/enqueued when disabled


@pytest.mark.asyncio
async def test_tick_enqueues_one_job_per_auto_sync_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(external_source_sync_enabled=True),
    )
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


def test_worker_uses_worker_session_not_web_pool() -> None:
    """Finding 21: the worker must use worker_session, never the web pool's async_session."""
    source = Path(w.__file__).read_text(encoding="utf-8")
    assert "from app.workers._db import worker_session" in source
    assert "from app.core.db import" not in source
    assert "async_session" not in source or "worker_session" in source


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
