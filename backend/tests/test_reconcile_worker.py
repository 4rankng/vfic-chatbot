"""Tests for reconcile_worker — tick flow and loop-safety invariants.

Pure unit tests with mocked dependencies. Critical assertions:
- SETNX guard prevents overlapping ticks
- acquire_lock False → skip (double-tick idempotency)
- run_start_guard False → skip (mode gating)
- enqueue fail → release_lock + enqueue_failed counter
- Happy path → enqueue called + re_enqueued counter
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.workers.reconcile_worker import _sweep, _run_tick_async


# --- helpers ---


def _make_conv(
    *,
    mode: ConversationMode = ConversationMode.BOT,
    status: ConversationStatus = ConversationStatus.OPEN,
    version: int = 1,
    zalo_chat_id: str = "test-zalo-id",
) -> Conversation:
    conv = Conversation(zalo_chat_id=zalo_chat_id, mode=mode, status=status, version=version)
    conv.id = uuid.uuid4()
    return conv


def _make_worker_msg(body: str = "xin chào") -> Message:
    msg = Message(
        sender=MessageSender.WORKER,
        delivery_status=DeliveryStatus.PENDING,
        body=body,
        conversation_id=uuid.uuid4(),
    )
    msg.id = 1
    msg.created_at = datetime(2026, 6, 30, 11, 50, 0, tzinfo=timezone.utc)
    return msg


def _make_bot_msg(
    *,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    body: str = "Đang soạn trả lời...",
) -> Message:
    msg = Message(
        sender=MessageSender.BOT,
        delivery_status=status,
        body=body,
        conversation_id=uuid.uuid4(),
    )
    msg.id = 2
    msg.created_at = datetime(2026, 6, 30, 11, 51, 0, tzinfo=timezone.utc)
    return msg


def _mock_db_for_scan(candidates: list) -> AsyncMock:
    """Mock db session for the initial candidate scan."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = candidates
    db.scalars = AsyncMock(return_value=mock_result)
    return db


def _mock_db_for_process(
    conv: Conversation,
    worker_msg: Message | None = None,
    latest_msg: Message | None = None,
    lock_acquired: bool = True,
) -> AsyncMock:
    """Mock db session for per-candidate processing."""
    db = AsyncMock()
    # svc.get(conv.id) → repo.get → db.get(Conversation, id)
    db.get = AsyncMock(return_value=conv)
    # acquire_lock + mark_stale_pending_failed both call db.execute(update(...))
    execute_result = MagicMock()
    execute_result.rowcount = 1 if lock_acquired else 0
    db.execute = AsyncMock(return_value=execute_result)
    def _scalar_result(value: Message | None) -> MagicMock:
        result = MagicMock()
        result.first.return_value = value
        return result

    actual_latest = latest_msg if latest_msg is not None else worker_msg
    if actual_latest is not None and actual_latest.sender == MessageSender.BOT:
        db.scalars = AsyncMock(
            side_effect=[
                _scalar_result(actual_latest),
                _scalar_result(worker_msg),
            ]
        )
    else:
        db.scalars = AsyncMock(return_value=_scalar_result(actual_latest))
    return db


def _mock_redis(*, setnx_ok: bool = True) -> MagicMock:
    """Mock sync Redis client."""
    redis = MagicMock()
    redis.set.return_value = setnx_ok
    redis.get.return_value = b"0"
    redis.pipeline.return_value = redis
    return redis


# Patch targets use SOURCE modules because all imports in reconcile_worker
# are lazy (inside function bodies), not at module level.
_PATCH_SESSION = "app.workers._db.worker_session"
_PATCH_ENQUEUE = "app.workers.chatbot_worker.enqueue_chat_run"
_PATCH_REDIS = "app.core.redis.get_redis_sync"


# --- SETNX non-reentrancy ---


@patch(_PATCH_REDIS)
async def test_setnx_guard_skips_when_held(mock_get_redis):
    """If a prior tick is still running, the new tick returns immediately."""
    mock_get_redis.return_value = _mock_redis(setnx_ok=False)

    await _run_tick_async()

    mock_get_redis.assert_called_once()


# --- No candidates ---


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_no_candidates_is_noop(mock_session_cls, mock_enqueue):
    """Empty candidate list → no enqueue, gauge set to 0."""
    mock_redis = _mock_redis()
    mock_db = _mock_db_for_scan([])
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_db
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    mock_redis.set.assert_any_call("reconcile_unanswered_gauge", "0")


# --- Happy path ---


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_happy_path_enqueues_recovery(mock_session_cls, mock_enqueue):
    """One candidate with WORKER newest → acquire_lock → enqueue_chat_run called."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg()

    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    call_kwargs = mock_enqueue.call_args[0][0]
    assert call_kwargs["conversation_id"] == str(conv.id)
    assert call_kwargs["version_at_start"] == conv.version
    assert call_kwargs["user_text"] == "xin chào"
    assert uuid.UUID(call_kwargs["lock_owner"])
    assert mock_redis.incrby.call_count >= 1
    mock_redis.set.assert_any_call("reconcile_unanswered_gauge", "1")


# --- Double-tick idempotency: acquire_lock False ---


@patch(_PATCH_ENQUEUE)
@patch(_PATCH_SESSION)
async def test_skip_locked_conversation(mock_session_cls, mock_enqueue):
    """If acquire_lock returns False (conversation already in-flight), skip it."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg()

    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, lock_acquired=False)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    mock_redis.incrby.assert_any_call("reconcile_skipped_locked_total", 1)


# --- SEMI_AUTO gating: human active → skip ---


@patch(_PATCH_ENQUEUE)
@patch(_PATCH_SESSION)
async def test_semi_auto_active_human_skipped(mock_session_cls, mock_enqueue):
    """SEMI_AUTO with recent taken_over_at → run_start_guard False → skip."""
    mock_redis = _mock_redis()
    conv = _make_conv(mode=ConversationMode.SEMI_AUTO)
    conv.taken_over_at = datetime.now(timezone.utc)

    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, _make_worker_msg())
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()


# --- SEMI_AUTO gating: human inactive → enqueue ---


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_semi_auto_inactive_human_enqueued(mock_session_cls, mock_enqueue):
    """SEMI_AUTO with old taken_over_at → run_start_guard True → enqueue."""
    mock_redis = _mock_redis()
    conv = _make_conv(mode=ConversationMode.SEMI_AUTO)
    conv.taken_over_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, _make_worker_msg())
    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()


# --- Enqueue fails → release_lock + counter ---


@patch(_PATCH_ENQUEUE, return_value=False)
@patch(_PATCH_SESSION)
async def test_enqueue_fail_releases_lock(mock_session_cls, mock_enqueue):
    """If enqueue_chat_run returns False (backpressure), release_lock is called."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, _make_worker_msg())

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    mock_redis.incrby.assert_any_call("reconcile_enqueue_failed_total", 1)
    assert conv.bot_locked_until is None


# --- Conversation vanished during sweep ---


@patch(_PATCH_ENQUEUE)
@patch(_PATCH_SESSION)
async def test_conversation_vanished_is_skipped(mock_session_cls, mock_enqueue):
    """If svc.get() returns None (conversation deleted), skip gracefully."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, _make_worker_msg())
    mock_db_proc.get = AsyncMock(return_value=None)  # conv vanished

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()


# --- mark_stale_pending_failed is called ---


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_mark_stale_pending_called(mock_session_cls, mock_enqueue):
    """mark_stale_pending_failed is called after acquire_lock succeeds."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg()
    bot_msg = _make_bot_msg(status=DeliveryStatus.PENDING)
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    assert mock_db_proc.execute.called
    mock_redis.incrby.assert_any_call("reconcile_stale_pending_total", 1)


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_failed_bot_send_is_reenqueued(mock_session_cls, mock_enqueue):
    """BOT/FAILED newest means Zalo rejected delivery; retry latest worker text."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    failed_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(
        conv,
        worker_msg,
        latest_msg=failed_bot_msg,
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0]["user_text"] == "bạn ăn tối chưa?"
    mock_redis.incrby.assert_any_call("reconcile_failed_send_total", 1)
