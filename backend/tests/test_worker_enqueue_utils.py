from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.core import redis
from app.workers.utils import EnqueueStatusUnknown, enqueue_job


def _job() -> None:
    return None


def test_enqueue_job_preserves_boolean_contract_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeQueue:
        count = 0

        def __init__(self, _name, *, connection):
            assert connection is not None

        def enqueue(self, _fn, *_args, **_kwargs):
            return SimpleNamespace(id="rq-job-1")

    monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=FakeQueue))
    monkeypatch.setattr(redis, "get_redis_sync", object)

    assert enqueue_job("ingest", _job) is True
    assert enqueue_job("ingest", _job, return_job_id=True) == "rq-job-1"


def test_enqueue_job_uses_mode_specific_failure_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingQueue:
        count = 0

        def __init__(self, _name, *, connection):
            assert connection is not None

        def enqueue(self, _fn, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=FailingQueue))
    monkeypatch.setattr(redis, "get_redis_sync", object)

    assert enqueue_job("ingest", _job) is False
    assert enqueue_job("ingest", _job, return_job_id=True) is None


def test_named_enqueue_reconciles_an_accepted_job_after_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()

    class AmbiguousQueue:
        count = 0

        def __init__(self, _name, *, connection):
            assert connection is not None

        def enqueue(self, _fn, *_args, **_kwargs):
            raise ConnectionError("response lost after enqueue")

    class ExistingJob:
        @classmethod
        def fetch(cls, job_id, *, connection):
            assert job_id == "revision-1"
            return cls()

        def get_status(self):
            return SimpleNamespace(value="queued")

    monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=AmbiguousQueue))
    monkeypatch.setitem(sys.modules, "rq.job", SimpleNamespace(Job=ExistingJob))
    monkeypatch.setattr(redis, "get_redis_sync", lambda: connection)

    assert (
        enqueue_job("ingest", _job, return_job_id=True, job_id="revision-1") == "revision-1"
    )


def test_named_enqueue_surfaces_unknown_receipt_without_claiming_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingJobError(Exception):
        pass

    class AmbiguousQueue:
        count = 0

        def __init__(self, _name, *, connection):
            assert connection is not None

        def enqueue(self, _fn, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    class UnreachableJob:
        @classmethod
        def fetch(cls, _job_id, *, connection):
            raise ConnectionError("receipt unavailable")

    monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=AmbiguousQueue))
    monkeypatch.setitem(sys.modules, "rq.job", SimpleNamespace(Job=UnreachableJob))
    monkeypatch.setitem(
        sys.modules,
        "rq.exceptions",
        SimpleNamespace(NoSuchJobError=MissingJobError),
    )
    monkeypatch.setattr(redis, "get_redis_sync", object)

    with pytest.raises(EnqueueStatusUnknown, match="revision-2"):
        enqueue_job("ingest", _job, return_job_id=True, job_id="revision-2")


def test_named_enqueue_requeues_a_retained_failed_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requeued: list[bool] = []

    class DuplicateQueue:
        count = 0

        def __init__(self, _name, *, connection):
            assert connection is not None

        def enqueue(self, _fn, *_args, **_kwargs):
            raise RuntimeError("duplicate job id")

    class FailedJob:
        @classmethod
        def fetch(cls, _job_id, *, connection):
            return cls()

        def get_status(self):
            return SimpleNamespace(value="failed")

        def requeue(self):
            requeued.append(True)

    monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=DuplicateQueue))
    monkeypatch.setitem(sys.modules, "rq.job", SimpleNamespace(Job=FailedJob))
    monkeypatch.setattr(redis, "get_redis_sync", object)

    assert enqueue_job("ingest", _job, return_job_id=True, job_id="revision-3") == "revision-3"
    assert requeued == [True]


def test_recovered_turns_use_their_own_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live candidate turns and recovered turns must not share one queue.

    worker-chatbot consumes webhook_high first and recovery second, so a recovery
    backlog (dozens of turns after an outage) can never delay a live turn.
    """
    from app.workers import chatbot_worker

    seen: list[str] = []

    def fake_enqueue(queue_name, *_args, **_kwargs):
        seen.append(queue_name)
        return True

    monkeypatch.setattr("app.workers.utils.enqueue_job", fake_enqueue)

    assert chatbot_worker.enqueue_chat_run({"conversation_id": "live"}) is True
    assert chatbot_worker.enqueue_recovery_chat_run({"conversation_id": "recovered"}) is True
    assert seen == ["webhook_high", "recovery"]
