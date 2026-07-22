"""Hermetic tests for the single-page external-source sync worker."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.project.single_page_external_sources import SinglePageExternalSourceSyncOutcome
from app.services.knowledge.external_source_sync import ExternalSourceSyncError
from app.models.user import Role
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


@pytest.mark.asyncio
async def test_run_job_async_marks_missing_actor_failed_and_keeps_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(
        id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        last_status="NEW",
        last_error=None,
        last_synced_at=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))
    monkeypatch.setattr(
        w,
        "_resolve_actor",
        AsyncMock(side_effect=ExternalSourceSyncError("no_sync_actor")),
    )
    counters = []
    monkeypatch.setattr(w, "_bump_counter", lambda key: counters.append(key))

    with pytest.raises(RuntimeError, match="no_sync_actor"):
        await w._run_job_async(state.id)

    assert state.last_status == "FAILED"
    assert state.last_error == "no_sync_actor"
    assert state.last_synced_at is not None
    db.commit.assert_awaited_once()
    assert w.COUNTER_FAILURE in counters


def test_enqueue_configures_bounded_worker_crash_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _enqueue(*_args, **kwargs):
        captured.update(kwargs)
        return "job-id"

    monkeypatch.setattr("app.workers.utils.enqueue_job", _enqueue)

    assert w.enqueue_one_shot(uuid.uuid4()) == "job-id"
    retry = captured["retry"]
    assert retry.max == 3
    assert retry.intervals == [2000, 2000, 2000]


@pytest.mark.asyncio
async def test_run_job_async_keeps_locked_job_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))
    monkeypatch.setattr(
        w, "_resolve_actor", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    )
    monkeypatch.setattr(
        "app.services.project.single_page_external_sources.sync_single_page_external_source",
        AsyncMock(return_value=SinglePageExternalSourceSyncOutcome(status="LOCKED")),
    )

    with pytest.raises(RuntimeError, match="single_page_external_source_sync_locked"):
        await w._run_job_async(state.id)


@pytest.mark.asyncio
async def test_resolve_actor_uses_enabled_admin_creator() -> None:
    creator = SimpleNamespace(id=uuid.uuid4(), role=Role.admin, disabled=False)
    db = AsyncMock()
    db.get = AsyncMock(return_value=creator)

    assert await w._resolve_actor(db, SimpleNamespace(created_by=creator.id)) is creator
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "creator",
    [
        SimpleNamespace(id=uuid.uuid4(), role=Role.recruiter, disabled=False),
        SimpleNamespace(id=uuid.uuid4(), role=Role.admin, disabled=True),
    ],
)
async def test_resolve_actor_rejects_demoted_or_disabled_creator(creator) -> None:
    fallback = SimpleNamespace(id=uuid.uuid4(), role=Role.admin, disabled=False)
    db = AsyncMock()
    db.get = AsyncMock(return_value=creator)
    db.scalar = AsyncMock(return_value=fallback)

    assert await w._resolve_actor(db, SimpleNamespace(id=uuid.uuid4(), created_by=creator.id)) is fallback


@pytest.mark.asyncio
async def test_resolve_actor_fails_without_enabled_admin() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ExternalSourceSyncError, match="no_sync_actor"):
        await w._resolve_actor(db, SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4()))
