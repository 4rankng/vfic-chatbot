"""The TingTing OA processing gate in the shared chat-turn runner.

When the admin switch (``tingting_oa_enabled``) is off, a turn on the TingTing
OA stands down immediately before ``run_turn``: no graph run, no LLM outcome,
no reply. The turn is still recorded (SUPPRESSED, lock owner passed) so the
per-chat mutex clears and the dashboard keeps the audit row. Every other
account is untouched, and a broken account/settings read fails open.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.chatbot_worker import _run_job_async

_PATCH_SESSION = "app.workers._db.worker_session"
_PATCH_FACTORY = "app.workers._db.worker_session_factory"
_PATCH_DEPS = "app.graph.factories.build_deps"
_PATCH_RUN_TURN = "app.graph.runner.run_turn"
_PATCH_SERVICE = "app.services.conversation.ConversationService"
_PATCH_REDIS = "app.core.redis.get_redis_sync"
_PATCH_ENQUEUE = "app.workers.chatbot_worker.enqueue_recovery_chat_run"
_PATCH_ACCOUNT = "app.graph.factories.resolve_zalo_account_key"
_PATCH_ENABLED = "app.services.tingting_oa.processing_enabled"

TINGTING = "tingting"


def _job(conv) -> dict:
    return {
        "conversation_id": str(conv.id),
        "version_at_start": conv.version,
        "user_text": "Cho hỏi cách đặt lại mật khẩu",
        "user_name": "",
        "reply_to_message_id": "",
        "lock_owner": str(uuid.uuid4()),
        "received_at_epoch": 0.0,
        "trace_id": "trace-1",
    }


def _svc(conv):
    """ConversationPort stub recording the stand-down outcome."""
    svc = MagicMock()
    svc.get = AsyncMock(return_value=conv)
    svc.record_bot_outcome = AsyncMock()
    return svc


def _session() -> AsyncMock:
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


async def _run(
    job: dict,
    svc,
    *,
    account_key: str | None = TINGTING,
    enabled: bool = True,
    account_error: bool = False,
) -> AsyncMock:
    """Drive the real worker job body with the heavy deps stubbed out."""
    run_turn = AsyncMock()
    account = AsyncMock(return_value=account_key)
    if account_error:
        account = AsyncMock(side_effect=RuntimeError("identity read failed"))
    with patch(_PATCH_SESSION, return_value=_session()):
        with patch(_PATCH_FACTORY, return_value=MagicMock()):
            with patch(_PATCH_DEPS, new_callable=AsyncMock, return_value=MagicMock()):
                with patch(_PATCH_RUN_TURN, run_turn):
                    with patch(_PATCH_SERVICE, return_value=svc):
                        with patch(_PATCH_REDIS, side_effect=RuntimeError("no redis")):
                            with patch(_PATCH_ENQUEUE, return_value=True):
                                with patch(_PATCH_ACCOUNT, account):
                                    with patch(
                                        _PATCH_ENABLED,
                                        AsyncMock(return_value=enabled),
                                    ):
                                        await _run_job_async(job)
    return run_turn


@pytest.mark.asyncio
async def test_disabled_switch_stands_the_turn_down_without_an_llm_run():
    conv = MagicMock(id=uuid.uuid4(), version=3)
    svc = _svc(conv)
    job = _job(conv)

    run_turn = await _run(job, svc, account_key=TINGTING, enabled=False)

    run_turn.assert_not_called()
    svc.record_bot_outcome.assert_awaited_once()
    kwargs = svc.record_bot_outcome.call_args.kwargs
    assert kwargs["sent"] is False
    assert kwargs["reply"] == ""
    assert kwargs["lock_owner"] == job["lock_owner"], "the stand-down clears the mutex"
    assert kwargs["version_at_start"] == conv.version


@pytest.mark.asyncio
async def test_enabled_switch_runs_the_turn_as_before():
    conv = MagicMock(id=uuid.uuid4(), version=3)
    svc = _svc(conv)

    run_turn = await _run(_job(conv), svc, account_key=TINGTING, enabled=True)

    run_turn.assert_awaited_once()
    svc.record_bot_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_other_account_ignores_the_switch():
    """The default Zalo bot (no account key) never stands down, flag or no flag."""
    conv = MagicMock(id=uuid.uuid4(), version=3)
    svc = _svc(conv)

    run_turn = await _run(_job(conv), svc, account_key=None, enabled=False)

    run_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_account_read_failure_fails_open():
    conv = MagicMock(id=uuid.uuid4(), version=3)
    svc = _svc(conv)

    run_turn = await _run(_job(conv), svc, account_error=True, enabled=False)

    run_turn.assert_awaited_once()
    svc.record_bot_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_stand_down_survives_a_failed_outcome_record():
    """The gate is a guard, not a turn: a recording failure must not crash the job."""
    conv = MagicMock(id=uuid.uuid4(), version=3)
    svc = _svc(conv)
    svc.record_bot_outcome = AsyncMock(side_effect=RuntimeError("write failed"))

    run_turn = await _run(_job(conv), svc, account_key=TINGTING, enabled=False)

    run_turn.assert_not_called()
    svc.record_bot_outcome.assert_awaited_once()
