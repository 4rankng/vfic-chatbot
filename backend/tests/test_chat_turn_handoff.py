"""A message that arrives while a turn holds the per-chat mutex still gets a turn.

The ingress guard refuses a second inbound for a locked conversation: the
message is persisted, but no job is enqueued for it. Nothing else picks it up.
The reconcile sweep only considers a conversation whose NEWEST message is WORKER
or a BOT PENDING/SENDING/FAILED row, and the in-flight turn's own outcome row
(SENT or SUPPRESSED) is written *after* the dropped message — so the newest
message is a BOT row and the sweep skips the conversation forever. The candidate
is left with no answer to either message.

The turn that held the mutex therefore hands over: once it is done (and its lock
is released), if the newest inbound is not the one it answered, one turn is
enqueued for the newest unanswered inbound. The hand-off is bounded by
construction — the handed-over turn answers the newest message, so its own
hand-off finds the newest inbound is the one it handled and stops; a turn that
failed on its own message (agent crash, throttle) leaves the newest inbound as
the one it handled and never re-enqueues itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.graph.llm_semaphore import LLMThrottled
from app.workers.chatbot_worker import _run_job_async

_PATCH_SESSION = "app.workers._db.worker_session"
_PATCH_FACTORY = "app.workers._db.worker_session_factory"
_PATCH_DEPS = "app.graph.factories.build_deps"
_PATCH_RUN_TURN = "app.graph.runner.run_turn"
_PATCH_SERVICE = "app.services.conversation.ConversationService"
_PATCH_REDIS = "app.core.redis.get_redis_sync"
_PATCH_ENQUEUE = "app.workers.chatbot_worker.enqueue_recovery_chat_run"

_MISSING = object()


def _conv(version: int = 4):
    return SimpleNamespace(id=uuid.uuid4(), version=version, mode="BOT")


def _inbound(body: str, provider_id: str, *, row_id: int = 1):
    return SimpleNamespace(
        id=row_id,
        body=body,
        provider_message_id=provider_id,
        zalo_message_id=provider_id,
        created_at=datetime.now(timezone.utc),
    )


class _Svc:
    """ConversationPort stub: the newest inbound plus a free per-chat mutex."""

    def __init__(self, conv, newest, *, unanswered=_MISSING, raises: bool = False, bot_may_run=True):
        self._conv = conv
        self._newest = newest
        self._unanswered = newest if unanswered is _MISSING else unanswered
        self._raises = raises
        self._bot_may_run = bot_may_run
        self.lock_calls = 0
        self.recorded: list[dict] = []

    def run_start_guard(self, _conv):
        return self._bot_may_run

    async def get(self, _id):
        return self._conv

    async def latest_worker_message(self, _conv):
        if self._raises:
            raise RuntimeError("newest-inbound read failed")
        return self._newest

    async def latest_unanswered_worker_message(self, _conv):
        return self._unanswered

    async def acquire_lock(self, _conv_id):
        self.lock_calls += 1
        return uuid.uuid4()

    async def release_lock(self, _conv, lock_owner=None):
        return None

    async def record_bot_outcome(self, _conv, **kwargs):
        self.recorded.append(kwargs)


def _job(conv, *, answered: str, user_text: str = "Chào") -> dict:
    return {
        "conversation_id": str(conv.id),
        "version_at_start": conv.version,
        "user_text": user_text,
        "user_name": "",
        "reply_to_message_id": answered,
        "lock_owner": str(uuid.uuid4()),
        "received_at_epoch": 0.0,
        "trace_id": "trace-1",
    }


def _session() -> AsyncMock:
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


async def _run(job: dict, svc, captured: list[dict], *, turn=None) -> None:
    """Drive the real worker job body with the heavy deps stubbed out."""
    run_turn = AsyncMock(side_effect=turn) if turn is not None else AsyncMock()
    with patch(_PATCH_SESSION, return_value=_session()):
        with patch(_PATCH_FACTORY, return_value=MagicMock()):
            with patch(_PATCH_DEPS, new_callable=AsyncMock, return_value=MagicMock()):
                with patch(_PATCH_RUN_TURN, run_turn):
                    with patch(_PATCH_SERVICE, return_value=svc):
                        with patch(_PATCH_REDIS, side_effect=RuntimeError("no redis")):
                            with patch(
                                _PATCH_ENQUEUE,
                                side_effect=lambda payload: captured.append(payload) or True,
                            ):
                                await _run_job_async(job)


@pytest.mark.asyncio
async def test_second_inbound_arriving_mid_turn_gets_its_own_turn():
    """'Chào' is in flight; 'Hello' lands and the ingress guard refuses it.

    The turn for 'Chào' finishes, sees the newest inbound is 'Hello', and hands
    the conversation over — otherwise 'Hello' is never answered.
    """
    conv = _conv()
    svc = _Svc(conv, _inbound("Hello", "msg-2", row_id=2))
    captured: list[dict] = []

    await _run(_job(conv, answered="msg-1"), svc, captured)

    assert len(captured) == 1, "the dropped inbound must still get a turn"
    assert captured[0]["conversation_id"] == str(conv.id)
    assert captured[0]["user_text"] == "Hello"
    assert captured[0]["version_at_start"] == conv.version


@pytest.mark.asyncio
async def test_throttled_turn_still_hands_over_a_newer_inbound():
    """A suppressed (throttled) turn owns the mutex too — it must hand over as well."""
    conv = _conv()
    svc = _Svc(conv, _inbound("Hello", "msg-2", row_id=2))
    captured: list[dict] = []

    await _run(
        _job(conv, answered="msg-1"),
        svc,
        captured,
        turn=LLMThrottled("rate limit"),
    )

    assert [payload["user_text"] for payload in captured] == ["Hello"]


@pytest.mark.asyncio
async def test_turn_answering_the_newest_inbound_never_re_enqueues_itself():
    """Anti-loop: a turn that failed on its own message must not hand itself over.

    This is what keeps an agent-crash suppression from re-answering the same
    inbound every turn (the reconcile re-enqueue storm).
    """
    conv = _conv()
    svc = _Svc(conv, _inbound("Chào", "msg-1"))
    captured: list[dict] = []

    await _run(_job(conv, answered="msg-1"), svc, captured)

    assert captured == []
    assert svc.lock_calls == 0


@pytest.mark.asyncio
async def test_already_answered_newest_inbound_is_not_re_answered():
    """A concurrent turn may have answered the newest inbound already — no duplicate."""
    conv = _conv()
    svc = _Svc(conv, _inbound("Hello", "msg-2", row_id=2), unanswered=None)
    captured: list[dict] = []

    await _run(_job(conv, answered="msg-1"), svc, captured)

    assert captured == []


@pytest.mark.asyncio
async def test_direct_turn_without_an_inbound_id_never_hands_over():
    """Web-chat/direct turns carry no inbound provider id: never guess a hand-off."""
    conv = _conv()
    svc = _Svc(conv, _inbound("Chào", "msg-1"))
    captured: list[dict] = []

    await _run(_job(conv, answered=""), svc, captured)

    assert captured == []


@pytest.mark.asyncio
async def test_human_owned_conversation_is_never_handed_over():
    """A recruiter owns the chat now (HUMAN / active SEMI_AUTO): the bot stays out."""
    conv = _conv()
    svc = _Svc(conv, _inbound("Hello", "msg-2", row_id=2), bot_may_run=False)
    captured: list[dict] = []

    await _run(_job(conv, answered="msg-1"), svc, captured)

    assert captured == []
    assert svc.lock_calls == 0


@pytest.mark.asyncio
async def test_handoff_failure_never_breaks_the_turn():
    """The hand-off is recovery plumbing: a read failure must not crash the worker."""
    conv = _conv()
    svc = _Svc(conv, _inbound("Hello", "msg-2", row_id=2), raises=True)
    captured: list[dict] = []

    await _run(_job(conv, answered="msg-1"), svc, captured)

    assert captured == []
