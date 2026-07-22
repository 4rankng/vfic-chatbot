"""Hermetic tests for the single-page external-source sync worker."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.project.single_page_external_sources import SinglePageExternalSourceSyncOutcome
from app.workers import single_page_external_source_sync_worker as w


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
async def test_tick_enqueues_one_job_per_auto_sync_row(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]
    enqueued = []
    monkeypatch.setattr(
        w,
        "enqueue_one_shot",
        lambda state_id, job_id=None: enqueued.append((str(state_id), job_id)) or f"job-{state_id}",
    )
    monkeypatch.setattr(
        "app.workers._db.worker_session",
        lambda: _FakeSessionCM(_db_returning_state_ids(ids)),
    )

    await w._tick_async()
    assert len(enqueued) == 2
    for state_id, job_id in enqueued:
        assert job_id.startswith(f"single-page-ext-src-sync-{state_id}-")


@pytest.mark.asyncio
async def test_run_job_async_invokes_orchestrator_and_bumps_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))
    monkeypatch.setattr(w, "_resolve_actor", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.sync_single_page_external_source",
        AsyncMock(
            return_value=SinglePageExternalSourceSyncOutcome(
                status="OK",
                content_hash="abcd1234",
                row_count=5,
            )
        ),
    )
    counters = []
    monkeypatch.setattr(w, "_bump_counter", lambda key: counters.append(key))

    await w._run_job_async(state.id)
    assert w.COUNTER_SUCCESS in counters


@pytest.mark.asyncio
async def test_run_job_async_missing_state_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))

    await w._run_job_async(uuid.uuid4())
