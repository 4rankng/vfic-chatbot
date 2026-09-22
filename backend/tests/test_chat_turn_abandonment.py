"""Abandoned-turn recording: a turn that dies must leave an audit row.

RQ's death penalty raises ``JobTimeoutException`` *inside* the job, so the
worker's crash guard is the only place that sees a timed-out turn — and because
the guard suppresses it, RQ records the job as successful. Without an explicit
record the turn leaves no BotRun, no lock release, and no dashboard signal: the
reconcile sweep then re-answers the same conversation every ~60s forever.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rq.timeouts import JobTimeoutException

from app.models.conversation import DeliveryStatus
from app.workers.chatbot_worker import _run_job_async

_PATCH_INNER = "app.workers.chatbot_worker._run_job_async_inner"
_PATCH_SESSION = "app.workers._db.worker_session"
_PATCH_SERVICE = "app.services.conversation.ConversationService"


def _job() -> dict:
    return {
        "conversation_id": str(uuid.uuid4()),
        "version_at_start": 7,
        "user_text": "hello",
        "lock_owner": str(uuid.uuid4()),
        "received_at_epoch": 0.0,
        "trace_id": "trace-1",
    }


def _mock_session() -> AsyncMock:
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


def _mock_service() -> MagicMock:
    svc = MagicMock()
    svc.get = AsyncMock(return_value=MagicMock(version=7))
    svc.record_bot_outcome = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_timed_out_turn_records_pending_audit_row():
    """A job-timeout kill is recorded, not silently swallowed."""
    job = _job()
    svc = _mock_service()

    with patch(_PATCH_INNER, new=AsyncMock(side_effect=JobTimeoutException("slow"))):
        with patch(_PATCH_SESSION, return_value=_mock_session()):
            with patch(_PATCH_SERVICE, return_value=svc):
                await _run_job_async(job)

    assert svc.record_bot_outcome.call_count == 1
    kwargs = svc.record_bot_outcome.call_args.kwargs
    assert kwargs["sent"] is False
    assert kwargs["reply"] == ""
    # PENDING keeps the reconcile sweep's fast lost-turn recovery path; the
    # ERROR outcome comes from external_error being set.
    assert kwargs["delivery_status"] == DeliveryStatus.PENDING
    assert "timeout" in kwargs["external_error"]
    assert kwargs["version_at_start"] == 7
    assert kwargs["lock_owner"] == job["lock_owner"]
    assert kwargs["trace_id"] == "trace-1"
    assert kwargs["stage_timings"]["degraded"] is True


@pytest.mark.asyncio
async def test_crashed_turn_names_the_exception_type():
    """A non-timeout crash is recorded with its exception type for triage."""
    svc = _mock_service()

    with patch(_PATCH_INNER, new=AsyncMock(side_effect=ValueError("boom"))):
        with patch(_PATCH_SESSION, return_value=_mock_session()):
            with patch(_PATCH_SERVICE, return_value=svc):
                await _run_job_async(_job())

    kwargs = svc.record_bot_outcome.call_args.kwargs
    assert "ValueError" in kwargs["external_error"]


@pytest.mark.asyncio
async def test_vanished_conversation_does_not_crash_worker():
    """A deleted conversation must not turn a crash into a worker kill."""
    svc = _mock_service()
    svc.get = AsyncMock(return_value=None)

    with patch(_PATCH_INNER, new=AsyncMock(side_effect=ValueError("boom"))):
        with patch(_PATCH_SESSION, return_value=_mock_session()):
            with patch(_PATCH_SERVICE, return_value=svc):
                await _run_job_async(_job())

    svc.record_bot_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_recording_failure_does_not_crash_worker():
    """Recording is best-effort: the guard's worker-safety promise survives."""
    svc = _mock_service()
    svc.record_bot_outcome = AsyncMock(side_effect=RuntimeError("db down"))

    with patch(_PATCH_INNER, new=AsyncMock(side_effect=ValueError("boom"))):
        with patch(_PATCH_SESSION, return_value=_mock_session()):
            with patch(_PATCH_SERVICE, return_value=svc):
                await _run_job_async(_job())


@pytest.mark.asyncio
async def test_cancellation_still_propagates():
    """Shutdown must not be converted into a recorded outcome."""
    svc = _mock_service()

    with patch(_PATCH_INNER, new=AsyncMock(side_effect=KeyboardInterrupt())):
        with patch(_PATCH_SESSION, return_value=_mock_session()):
            with patch(_PATCH_SERVICE, return_value=svc):
                with pytest.raises(KeyboardInterrupt):
                    await _run_job_async(_job())

    svc.record_bot_outcome.assert_not_called()
