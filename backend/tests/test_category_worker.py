from __future__ import annotations

import uuid

import pytest

from app.workers import category_worker, utils
from app.workers.ingest_worker import enqueue_ingest_version
from app.services.knowledge.document_repository import mark_category_revision_failed_sync


def test_category_enqueue_returns_stable_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    revision_id = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_enqueue(queue_name, fn, *args, **kwargs):
        captured.update(queue_name=queue_name, fn=fn, args=args, kwargs=kwargs)
        return "category-job-123"

    monkeypatch.setattr(utils, "enqueue_job", fake_enqueue)

    assert category_worker.enqueue_category_revision(revision_id) == "category-job-123"
    assert captured["queue_name"] == "category"
    assert captured["fn"] is category_worker.run_category_revision_job
    assert captured["args"] == (str(revision_id),)
    assert captured["kwargs"]["return_job_id"] is True
    assert captured["kwargs"]["job_id"] == f"category-revision-{revision_id}"


def test_category_enqueue_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(utils, "enqueue_job", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="category revision enqueue failed"):
        category_worker.enqueue_category_revision(uuid.uuid4())


def test_legacy_version_enqueue_uses_same_job_id_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(utils, "enqueue_job", lambda *args, **kwargs: "version-job-456")

    version_id = uuid.uuid4()

    assert enqueue_ingest_version(version_id) == "version-job-456"


def test_outer_worker_failure_uses_fenced_marker_and_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision_id = str(uuid.uuid4())
    marked: list[tuple[str, uuid.UUID]] = []

    def fail(coroutine) -> None:
        coroutine.close()
        raise TimeoutError("provider payload must not escape")

    monkeypatch.setattr("app.workers.async_runner.run_async", fail)
    monkeypatch.setattr(
        category_worker,
        "_mark_category_revision_failed_sync",
        lambda value, token: marked.append((value, token)),
    )

    with pytest.raises(RuntimeError, match="category_worker_failed") as caught:
        category_worker.run_category_revision_job(revision_id)

    assert "provider payload" not in str(caught.value)
    assert marked and marked[0][0] == revision_id
    assert isinstance(marked[0][1], uuid.UUID)


def test_outer_failure_marker_handles_setup_failure_before_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: dict[str, object] = {}

    class _Connection:
        def execute(self, statement, params) -> None:
            executed["sql"] = str(statement)
            executed["params"] = params

    class _Begin:
        def __enter__(self) -> _Connection:
            return _Connection()

        def __exit__(self, *_args) -> None:
            return None

    class _Engine:
        def begin(self) -> _Begin:
            return _Begin()

        def dispose(self) -> None:
            return None

    monkeypatch.setattr("sqlalchemy.create_engine", lambda *_args, **_kwargs: _Engine())
    revision_id = str(uuid.uuid4())
    token = str(uuid.uuid4())

    mark_category_revision_failed_sync(
        "postgresql+psycopg://example.test/db",
        revision_id,
        token,
        "category_worker_failed",
    )

    assert "status = 'STAGED' AND processing_token IS NULL" in str(executed["sql"])
    assert "processing_token = CAST(:processing_token AS uuid)" in str(executed["sql"])
    assert executed["params"] == {
        "id": revision_id,
        "processing_token": token,
        "failure_code": "category_worker_failed",
    }
