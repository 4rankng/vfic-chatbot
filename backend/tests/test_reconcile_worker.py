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
    failed_send_attempts: int | None = None,
) -> AsyncMock:
    """Mock db session for per-candidate processing."""
    db = AsyncMock()
    # svc.get(conv.id) → repo.get → db.get(Conversation, id)
    db.get = AsyncMock(return_value=conv)
    # acquire_lock + mark_stale_pending_failed both call db.execute(update(...))
    execute_result = MagicMock()
    execute_result.rowcount = 1 if lock_acquired else 0
    db.execute = AsyncMock(return_value=execute_result)
    if failed_send_attempts is not None:
        # ``_failed_send_attempts`` counts refused replies through db.scalar.
        db.scalar = AsyncMock(return_value=failed_send_attempts)

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


_TICK_LOCK = "reconcile_tick_lock"


class _CasRedis:
    """Sync-Redis stand-in that models the tick-lock ownership contract.

    ``eval`` applies the release script's rule (delete the key only when the
    stored value is the caller's own id). ``delete`` raises: the tick lock must
    never be released blindly, so a regression back to ``conn.delete(...)`` fails
    loudly here. ``ttl_expired_to`` models the race the CAS closes — this tick's
    300 s TTL ran out mid-sweep and a successor tick already owns the key.
    """

    def __init__(self, *, ttl_expired_to: str | None = None) -> None:
        self.store: dict[str, str] = {}
        self.release_calls: list[tuple[str, str]] = []
        self.owner_value: str | None = None
        self._ttl_expired_to = ttl_expired_to

    def set(self, key, value, *, nx=False, ex=None):  # noqa: ANN001, ARG002
        if nx and key in self.store:
            return None
        self.store[key] = value
        if key == _TICK_LOCK:
            self.owner_value = value
        return True

    def eval(self, script, numkeys, key, owner):  # noqa: ANN001, ARG002
        from app.workers.reconcile_worker import _RELEASE_TICK_LOCK_LUA

        assert script == _RELEASE_TICK_LOCK_LUA
        self.release_calls.append((key, owner))
        if self._ttl_expired_to is not None:
            self.store[key] = self._ttl_expired_to
        if self.store.get(key) == owner:
            del self.store[key]
            return 1
        return 0

    def delete(self, *keys):  # noqa: ANN002, ARG002
        raise AssertionError("the tick lock must be released with an ownership CAS")

    def incrby(self, key, amount):  # noqa: ANN001, ARG002
        self.store[key] = int(self.store.get(key, 0)) + int(amount)
        return self.store[key]

    def pipeline(self):
        return self


# Patch targets use SOURCE modules because all imports in reconcile_worker
# are lazy (inside function bodies), not at module level.
_PATCH_SESSION = "app.workers._db.worker_session"
_PATCH_ENQUEUE = "app.workers.chatbot_worker.enqueue_recovery_chat_run"
_PATCH_REDIS = "app.core.redis.get_redis_sync"


# --- SETNX non-reentrancy ---


@patch(_PATCH_REDIS)
async def test_setnx_guard_skips_when_held(mock_get_redis):
    """If a prior tick is still running, the new tick returns immediately."""
    mock_get_redis.return_value = _mock_redis(setnx_ok=False)

    await _run_tick_async()

    mock_get_redis.assert_called_once()


@patch(_PATCH_SESSION)
@patch(_PATCH_REDIS)
async def test_tick_lock_is_released_by_its_own_owner(mock_get_redis, mock_session_cls):
    """The tick releases the lock with an ownership CAS, never a blind delete.

    The lock value is this tick's own UUID, so a release that raced a TTL expiry
    can prove ownership instead of deleting whatever is there.
    """
    redis = _CasRedis()
    mock_get_redis.return_value = redis
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = _mock_db_for_scan([])
    mock_session_cls.return_value = mock_cm

    await _run_tick_async()

    assert redis.owner_value is not None
    uuid.UUID(redis.owner_value)  # a per-tick identity, not a shared constant
    assert redis.release_calls == [("reconcile_tick_lock", redis.owner_value)]
    assert "reconcile_tick_lock" not in redis.store


@patch(_PATCH_SESSION)
@patch(_PATCH_REDIS)
async def test_tick_lock_survives_when_the_holder_is_not_the_owner(
    mock_get_redis, mock_session_cls
):
    """A tick whose TTL expired must not delete the successor's lock.

    Otherwise a slow sweep would release a lock it no longer owns and admit a
    third concurrent tick on top of the new owner.
    """
    redis = _CasRedis(ttl_expired_to="successor-tick")
    mock_get_redis.return_value = redis
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = _mock_db_for_scan([])
    mock_session_cls.return_value = mock_cm

    await _run_tick_async()

    assert redis.release_calls == [("reconcile_tick_lock", redis.owner_value)]
    assert redis.store["reconcile_tick_lock"] == "successor-tick"


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
    assert call_kwargs["execution_source"] == "recovery"
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
    conv.taken_over_at = datetime.now(timezone.utc) - timedelta(minutes=40)

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
async def test_partially_delivered_failed_answer_is_not_reenqueued(
    mock_session_cls, mock_enqueue
):
    """REL-01: a FAILED row carrying a provider message id is a partial delivery.

    The first bubble of a chunked answer reached the candidate before a later one
    failed, so re-answering would duplicate it. The row must not become a
    recovery turn — and it must not be counted as one either.
    """
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    partial_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    partial_bot_msg.provider_message_id = "chunk-1-mid"
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=partial_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    assert conv.bot_locked_until is None  # lock released for the next tick
    mock_redis.incrby.assert_any_call("reconcile_partial_delivery_skipped_total", 1)
    # It is a partial delivery, not a delivery-failure retry.
    counted = [call.args[0] for call in mock_redis.incrby.call_args_list]
    assert "reconcile_failed_send_total" not in counted


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_legacy_failed_row_with_only_a_zalo_id_is_not_reenqueued(
    mock_session_cls, mock_enqueue
):
    """The pre-0047 id column proves partial delivery just as well."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    partial_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    partial_bot_msg.zalo_message_id = "legacy-chunk-1-mid"
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=partial_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    mock_redis.incrby.assert_any_call("reconcile_partial_delivery_skipped_total", 1)


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


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_recent_delivery_failure_is_deferred(mock_session_cls, mock_enqueue):
    """A reply that just failed to deliver is not re-generated on the next tick.

    The FAILED row is what makes the conversation a candidate, so without a
    backoff an undeliverable conversation (unresolvable Page token, provider
    rejection) consumes a full LLM turn every ~2 minutes forever.
    """
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    failed_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    failed_bot_msg.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=failed_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    assert conv.bot_locked_until is None  # lock released for the next tick


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_delivery_failure_is_retried_once(mock_session_cls, mock_enqueue):
    """One refused reply still earns one recovery turn — that is the retry's job."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    failed_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    failed_bot_msg.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(
        conv, worker_msg, latest_msg=failed_bot_msg, failed_send_attempts=1
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    mock_redis.incrby.assert_any_call("reconcile_failed_send_total", 1)


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_delivery_failure_stops_after_two_attempts(mock_session_cls, mock_enqueue):
    """Two refused replies end the retry loop for that inbound.

    The retry itself writes the next FAILED row, so without a cap an
    undeliverable conversation is a permanent candidate — production re-answered
    the same inbound every ~16 minutes for hours, leaving the candidate a thread
    of identical undeliverable bubbles.
    """
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("bạn ăn tối chưa?")
    failed_bot_msg = _make_bot_msg(status=DeliveryStatus.FAILED, body="Không gửi được")
    failed_bot_msg.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(
        conv, worker_msg, latest_msg=failed_bot_msg, failed_send_attempts=2
    )

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    mock_redis.incrby.assert_any_call("reconcile_failed_send_exhausted_total", 1)
    assert conv.bot_locked_until is None  # lock released; a new inbound retries


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
async def test_recent_pending_is_still_recovered_fast(mock_session_cls, mock_enqueue):
    """Lost-turn recovery keeps its ~60s cadence; the backoff is only for FAILED."""
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("xin chào")
    pending_bot_msg = _make_bot_msg(status=DeliveryStatus.PENDING)
    pending_bot_msg.created_at = datetime.now(timezone.utc) - timedelta(seconds=130)
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=pending_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    mock_redis.incrby.assert_any_call("reconcile_stale_pending_total", 1)


# --- the durable net for an inbound dropped behind a completed outcome ---

_PATCH_NEVER_GIVEN = (
    "app.services.conversation.repository.ConversationRepository"
    ".latest_inbound_never_given_a_turn"
)


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
@patch(_PATCH_NEVER_GIVEN, new_callable=AsyncMock, return_value=True)
async def test_outcome_answering_an_older_inbound_recovers_the_dropped_message(
    mock_never_given, mock_session_cls, mock_enqueue
):
    """A completed outcome that answered an OLDER inbound leaves the newest message lost.

    The newest candidate message arrived while that outcome's turn held the
    per-chat mutex, so the ingress dropped it and its outcome row became the
    newest message — invisible to the loop-free predicate. The sweep recovers it
    and counts it apart from an ordinary never-processed inbound.
    """
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("Còn vị trí nào không?")
    sent_bot_msg = _make_bot_msg(status=DeliveryStatus.SENT, body="Dạ em chào anh")
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=sent_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_called_once()
    payload = mock_enqueue.call_args[0][0]
    assert payload["user_text"] == "Còn vị trí nào không?"
    assert payload["execution_source"] == "recovery"
    mock_redis.incrby.assert_any_call("reconcile_superseded_inbound_total", 1)


@patch(_PATCH_ENQUEUE, return_value=True)
@patch(_PATCH_SESSION)
@patch(_PATCH_NEVER_GIVEN, new_callable=AsyncMock, return_value=False)
async def test_outcome_that_answered_the_newest_message_is_not_recovered(
    mock_never_given, mock_session_cls, mock_enqueue
):
    """Re-verification against fresh state gates the action.

    Between the scan and the lock a turn may have answered the message; the
    outcome then quotes it, the proof fails, and the sweep must not enqueue a
    second answer to an already answered (or deliberately suppressed) message.
    """
    mock_redis = _mock_redis()
    conv = _make_conv()
    worker_msg = _make_worker_msg("Còn vị trí nào không?")
    sent_bot_msg = _make_bot_msg(status=DeliveryStatus.SENT, body="Dạ em chào anh")
    mock_db_scan = _mock_db_for_scan([conv])
    mock_db_proc = _mock_db_for_process(conv, worker_msg, latest_msg=sent_bot_msg)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.side_effect = [mock_db_scan, mock_db_proc]
    mock_session_cls.return_value = mock_cm

    await _sweep(mock_redis)

    mock_enqueue.assert_not_called()
    assert conv.bot_locked_until is None  # lock released for the next tick
    assert not any(
        call.args[0] == "reconcile_superseded_inbound_total"
        for call in mock_redis.incrby.call_args_list
    )
