"""Tests for Redis-backed LLM semaphore, 429 retry, and degradation path."""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.graph.llm_semaphore import (
    LLMThrottled,
    RedisLlmSemaphore,
    get_embed_semaphore,
)

# Patch target for lazy imports inside methods/functions:
# get_redis_sync is imported via `from app.core.redis import get_redis_sync`
# inside method bodies, so patch at the SOURCE module.
_REDIS_PATCH = "app.core.redis.get_redis_sync"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis():
    """In-memory fake Redis with enough BLPOP/RPUSH/LLEN semantics.

    Every token op records the thread it ran on (``op_threads``) so a test can
    assert the semaphore keeps them off the event loop.

    Thread-safe via a lock (needed for concurrent acquire tests where
    run_in_executor dispatches BLPOP to a thread pool).
    """
    store: dict[str, list] = {}
    lock = threading.Lock()

    r = MagicMock()
    # Annotated as a local bound onto the mock: a MagicMock attribute cannot
    # carry an annotation. The closures append through `r` and the assertions
    # read `fake_redis.op_threads` — the same list object either way.
    op_threads: list[threading.Thread] = []
    r.op_threads = op_threads

    def _rpush(key, *vals):
        with lock:
            r.op_threads.append(threading.current_thread())
            store.setdefault(key, []).extend(vals)

    def _blpop(key, timeout=0):
        with lock:
            r.op_threads.append(threading.current_thread())
            lst = store.get(key, [])
            if lst:
                return (key, lst.pop(0))
            return None  # timeout

    def _llen(key):
        with lock:
            return len(store.get(key, []))

    def _rpop(key):
        with lock:
            r.op_threads.append(threading.current_thread())
            lst = store.get(key, [])
            return lst.pop() if lst else None

    def _exists(key):
        with lock:
            r.op_threads.append(threading.current_thread())
            return 1 if key in store else 0

    r.rpush = MagicMock(side_effect=_rpush)
    r.blpop = MagicMock(side_effect=_blpop)
    r.llen = MagicMock(side_effect=_llen)
    r.rpop = MagicMock(side_effect=_rpop)
    r.exists = MagicMock(side_effect=_exists)
    r.persist = MagicMock(return_value=1)

    def _eval(script, numkeys, key, *args):
        # Emulates the release script under the fixture lock: push one
        # token, trim excess above the limit, return the resulting length.
        with lock:
            limit = int(args[0])
            lst = store.setdefault(key, [])
            lst.append(1)
            while len(lst) > limit:
                lst.pop()
            return len(lst)

    r.eval = MagicMock(side_effect=_eval)
    r.pipeline = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=[None])))
    return r


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons between tests."""
    import app.graph.llm_semaphore as mod

    old_sem, old_embed = mod._sem, mod._embed_sem
    mod._sem = None
    mod._embed_sem = None
    yield
    mod._sem = old_sem
    mod._embed_sem = old_embed


# ── RedisLlmSemaphore ────────────────────────────────────────────────────────


class TestDisabledSemaphore:
    """limit=0 means pass-through (no Redis ops)."""

    @pytest.mark.asyncio
    async def test_passthrough_does_not_call_redis(self):
        sem = RedisLlmSemaphore(limit=0)
        entered = False
        async with sem:
            entered = True
        assert entered

    @pytest.mark.asyncio
    async def test_passthrough_multiple_concurrent(self):
        sem = RedisLlmSemaphore(limit=0)
        results = await asyncio.gather(self._acquire(sem), self._acquire(sem), self._acquire(sem))
        assert all(r for r in results)

    @staticmethod
    async def _acquire(sem):
        async with sem:
            return True


class TestSemaphoreInit:
    """Lazy init populates N tokens on first acquire."""

    def test_ensure_tokens_populates(self, fake_redis):
        sem = RedisLlmSemaphore(limit=3, key="test_tokens")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
        assert fake_redis.llen("test_tokens") == 3
        assert sem._initialized

    def test_ensure_tokens_idempotent(self, fake_redis):
        sem = RedisLlmSemaphore(limit=2, key="test_tokens")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            sem._ensure_tokens()  # second call — no extra tokens
        assert fake_redis.llen("test_tokens") == 2
        assert fake_redis.rpush.call_count == 1  # only one RPUSH call


class TestSemaphoreAcquireRelease:
    """BLPOP acquires a token; RPUSH releases it in finally."""

    @pytest.mark.asyncio
    async def test_acquire_release_returns_token(self, fake_redis):
        sem = RedisLlmSemaphore(limit=2, key="test_sem")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            assert fake_redis.llen("test_sem") == 2

            async with sem:
                # Inside context: one token consumed
                assert fake_redis.llen("test_sem") == 1
            # After context: token returned
            assert fake_redis.llen("test_sem") == 2

    @pytest.mark.asyncio
    async def test_token_count_invariant(self, fake_redis):
        """Sequential acquire/release preserves token count (drift = 0)."""
        limit = 3
        sem = RedisLlmSemaphore(limit=limit, key="test_invariant")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            assert fake_redis.llen("test_invariant") == limit

            # Acquire and release N times sequentially — token count must stay at limit
            for _ in range(5):
                async with sem:
                    assert fake_redis.llen("test_invariant") == limit - 1
                assert fake_redis.llen("test_invariant") == limit

    @pytest.mark.asyncio
    async def test_token_ops_never_run_on_the_event_loop(self, fake_redis):
        """REL-02: every Redis command here is blocking, so none may run inline.

        The token bookkeeping, the release, and BLPOP all have to be dispatched
        off the loop — otherwise a slow Redis stalls webhook acks and every other
        concurrent turn with it.
        """
        sem = RedisLlmSemaphore(limit=1, key="test_off_loop")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            async with sem:
                pass

        assert fake_redis.op_threads, "no Redis command was recorded"
        assert all(thread is not threading.main_thread() for thread in fake_redis.op_threads), (
            "a semaphore Redis command ran on the event loop thread"
        )


class TestSemaphoreDriftDetection:
    """Drift > 1 emits warning; drift ≤ 1 is silent."""

    @pytest.mark.asyncio
    async def test_drift_within_tolerance_no_warning(self, fake_redis):
        sem = RedisLlmSemaphore(limit=3, key="test_drift_ok")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            async with sem:
                pass
            # After release: LLEN should be 3 (drift=0). Within tolerance.
            assert fake_redis.llen("test_drift_ok") == 3

    @pytest.mark.asyncio
    async def test_drift_shortfall_warns(self, fake_redis):
        """Excess above the limit is trimmed atomically by the release
        script, so after a release the warning fires only on a genuine
        shortfall: the count sitting more than one below the limit means
        tokens are held in flight (or leaked)."""
        sem = RedisLlmSemaphore(limit=3, key="test_drift_bad")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            # Drain the list so the release lands with a shortfall of 2.
            for _ in range(3):
                fake_redis.blpop("test_drift_bad", timeout=0)
            with patch("app.graph.llm_semaphore.logger") as mock_logger:
                sem._acquired = True
                sem._release_token()
                # Should have warned about drift (count 1 vs limit 3)
                mock_logger.warning.assert_called()


class TestSemaphoreTimeout:
    """BLPOP timeout fail-fasts (raises LLMThrottled, no silent degraded stall)."""

    @pytest.mark.asyncio
    async def test_timeout_raises_llm_throttled(self, fake_redis):
        """When BLPOP returns None (timeout), __aenter__ raises LLMThrottled so the
        worker suppresses the turn and clears the per-chat mutex."""
        sem = RedisLlmSemaphore(limit=1, key="test_timeout", acquire_timeout=0)
        sem._initialized = True  # skip token population → BLPOP returns None
        # The list is present but exhausted (every token checked out), so the
        # eviction self-heal must leave it alone and BLPOP must time out.
        fake_redis.exists = MagicMock(return_value=1)
        with patch(_REDIS_PATCH, return_value=fake_redis):
            with pytest.raises(LLMThrottled):
                async with sem:
                    pass


# ── LLMThrottled exception ─────────────────────────────────────────────────


class TestLLMThrottled:
    def test_is_exception(self):
        assert issubclass(LLMThrottled, Exception)

    def test_message(self):
        err = LLMThrottled("LLM rate limit exhausted after retry")
        assert "rate limit" in str(err)


# ── Embed semaphore ─────────────────────────────────────────────────────────


class TestEmbedSemaphore:
    def test_uses_different_key(self):
        sem = RedisLlmSemaphore(limit=5, key="llm_embed_sem_tokens")
        assert sem._key == "llm_embed_sem_tokens"

    def test_get_embed_semaphore_singleton(self):
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(embed_concurrency_limit=3)
            sem1 = get_embed_semaphore()
            sem2 = get_embed_semaphore()
            assert sem1 is sem2
            assert sem1._key == "llm_embed_sem_tokens"
            assert sem1._limit == 3


class TestSemaphoreEvictionSelfHeal:
    """allkeys-lru can evict the token list; the semaphore must self-heal.

    An evicted list with no in-flight holders never regrows and every BLPOP
    times out until restart (deployment-wide suppression). The recreate must
    key on the MISSING key only: a present-but-short list is tokens checked
    out under load, and topping it up would inflate the concurrency cap.
    """

    def test_ensure_tokens_recreates_evicted_list(self, fake_redis):
        sem = RedisLlmSemaphore(limit=3, key="test_evict")
        sem._initialized = True  # process registered before the eviction
        fake_redis.exists = MagicMock(return_value=0)  # key evicted
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
        fake_redis.rpush.assert_called_once_with("test_evict", 1, 1, 1)
        # Registration strips any TTL: volatile-lru evicts only TTL'd keys.
        fake_redis.persist.assert_called_once_with("test_evict")

    def test_ensure_tokens_keeps_present_but_short_list(self, fake_redis):
        """Saturation is not eviction: a present-but-short list is left alone."""
        sem = RedisLlmSemaphore(limit=3, key="test_present")
        sem._initialized = True
        fake_redis.exists = MagicMock(return_value=1)
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
        fake_redis.rpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_after_eviction_recreates_and_acquires(self, fake_redis):
        sem = RedisLlmSemaphore(limit=2, key="test_heal", acquire_timeout=0.01)
        sem._initialized = True
        fake_redis.exists = MagicMock(return_value=0)
        with patch(_REDIS_PATCH, return_value=fake_redis):
            async with sem:
                assert fake_redis.llen("test_heal") == 1
            assert fake_redis.llen("test_heal") == 2

    @pytest.mark.asyncio
    async def test_saturated_list_still_throttles_without_refill(self, fake_redis):
        """Key present but empty (all tokens checked out) raises LLMThrottled
        with NO refill: refilling would lift the cap under load."""
        sem = RedisLlmSemaphore(limit=2, key="test_sat_thr", acquire_timeout=0)
        sem._initialized = True
        fake_redis.exists = MagicMock(return_value=1)
        with patch(_REDIS_PATCH, return_value=fake_redis):
            with pytest.raises(LLMThrottled):
                async with sem:
                    pass
        fake_redis.rpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_prunes_refill_race_excess(self, fake_redis):
        """A concurrent recreate can leave more tokens than the limit; the
        next release prunes the excess back to the cap."""
        sem = RedisLlmSemaphore(limit=2, key="test_trim")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()  # registers 2 tokens
            fake_redis.rpush("test_trim", 1, 1)  # simulate a refill race -> 4
            async with sem:
                pass
            assert fake_redis.llen("test_trim") == 2
            # Release must go through the atomic Lua script, not three
            # racing round trips.
            fake_redis.eval.assert_called_once()


# ── 429 retry in clients ────────────────────────────────────────────────────


class TestRetry429:
    """_llm_call_with_retry retries once on 429 then raises LLMThrottled."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        from app.graph.provider_failover import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
        with patch("app.graph.provider_failover._record_llm_429", new_callable=AsyncMock):
            result, backoff_ms = await _llm_call_with_retry(bound, [])
        assert result.content == "ok"
        assert bound.ainvoke.call_count == 1
        assert backoff_ms == 0  # no backoff on the happy path

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        from app.graph.provider_failover import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(
            side_effect=[
                Exception("429 Too Many Requests"),
                MagicMock(content="retried ok"),
            ]
        )
        with patch("app.graph.provider_failover._record_llm_429", new_callable=AsyncMock) as mock_429:
            with patch("app.graph.provider_failover.asyncio.sleep", new_callable=AsyncMock):
                result, backoff_ms = await _llm_call_with_retry(bound, [])
        assert result.content == "retried ok"
        assert bound.ainvoke.call_count == 2
        mock_429.assert_called_once()
        assert backoff_ms >= 0  # backoff measured around the patched sleep

    @pytest.mark.asyncio
    async def test_raises_llm_throttled_on_double_429(self):
        from app.graph.provider_failover import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(
            side_effect=[
                Exception("429 rate limit exceeded"),
                Exception("429 rate limit exceeded"),
            ]
        )
        with patch("app.graph.provider_failover._record_llm_429", new_callable=AsyncMock):
            with patch("app.graph.provider_failover.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(LLMThrottled):
                    await _llm_call_with_retry(bound, [])

    @pytest.mark.asyncio
    async def test_no_retry_on_non_429_error(self):
        from app.graph.provider_failover import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            await _llm_call_with_retry(bound, [])
        assert bound.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_sleep_uses_configured_setting(self):
        """Retry sleep is settings.llm_429_retry_sleep_seconds (no hardcoded jitter)."""
        from app.core.config import get_settings
        from app.graph.provider_failover import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(
            side_effect=[
                Exception("429"),
                MagicMock(content="ok"),
            ]
        )
        sleep_args: list[float] = []

        async def _capture_sleep(delay):
            sleep_args.append(delay)

        with patch("app.graph.provider_failover._record_llm_429", new_callable=AsyncMock):
            with patch("app.graph.provider_failover.asyncio.sleep", side_effect=_capture_sleep):
                await _llm_call_with_retry(bound, [])
        assert len(sleep_args) == 1
        assert sleep_args[0] == get_settings().llm_429_retry_sleep_seconds


# ── LLM telemetry clients ───────────────────────────────────────────────────


class TestLlmTelemetryUsesAsyncRedis:
    """REL-02: the per-call counters must not run the blocking sync client.

    Both are written from inside the agent loop, where a sync Redis round trip
    blocks webhook acks and inline web-chat turns too. The key names + TTLs are
    the dashboard contract, so they must survive the switch.
    """

    @pytest.mark.asyncio
    async def test_429_counter_uses_async_client(self, monkeypatch):
        from app.core import redis as redis_mod
        from app.graph import clients as clients_mod

        class _R:
            def __init__(self):
                self.incrs: list[str] = []
                self.expires: list[tuple] = []

            async def incr(self, key):
                self.incrs.append(key)

            async def expire(self, key, ttl):
                self.expires.append((key, ttl))

        r = _R()

        async def _get_redis():
            return r

        monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
        monkeypatch.setattr(
            redis_mod, "get_redis_sync", lambda: pytest.fail("blocking sync redis on the loop")
        )

        await clients_mod._record_llm_429()

        assert r.incrs == [clients_mod._RKEY_429]
        assert r.expires == [(clients_mod._RKEY_429, 60)]  # rolling 1-minute window

    @pytest.mark.asyncio
    async def test_latency_counters_use_async_pipeline(self, monkeypatch):
        from app.core import redis as redis_mod
        from app.graph import clients as clients_mod

        class _Pipe:
            def __init__(self):
                self.ops: list[tuple] = []
                self.executed = False

            def incr(self, key):
                self.ops.append(("incr", key))
                return self

            def incrby(self, key, amount):
                self.ops.append(("incrby", key, amount))
                return self

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))
                return self

            async def execute(self):
                self.executed = True
                return [None] * len(self.ops)

        pipe = _Pipe()

        class _R:
            def pipeline(self):
                return pipe

        async def _get_redis():
            return _R()

        monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
        monkeypatch.setattr(
            redis_mod, "get_redis_sync", lambda: pytest.fail("blocking sync redis on the loop")
        )

        await clients_mod._record_llm_latency(250)

        assert pipe.executed
        assert ("incr", clients_mod._RKEY_INVOKE_COUNT) in pipe.ops
        assert ("incrby", clients_mod._RKEY_INVOKE_MS, 250) in pipe.ops
        assert ("expire", clients_mod._RKEY_INVOKE_COUNT, 120) in pipe.ops
        assert ("expire", clients_mod._RKEY_INVOKE_MS, 120) in pipe.ops


# ── Degradation path in worker ──────────────────────────────────────────────


class TestDegradationMessage:
    """chatbot_worker suppresses the turn on LLMThrottled — nothing is sent."""

    @pytest.mark.asyncio
    async def test_worker_catches_llm_throttled(self):
        """run_turn raising LLMThrottled sends NOTHING to the customer.

        All providers exhausted is an engineer problem, not a candidate-facing
        message: the turn is recorded as SUPPRESSED (lock cleared, dashboard
        keeps the degraded-turn audit row) and the sender is never touched.
        """
        from app.workers.chatbot_worker import _run_job_async

        job = {
            "conversation_id": str(uuid.uuid4()),
            "version_at_start": 1,
            "user_text": "hello",
            "user_name": "Test",
        }

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_conv = MagicMock()
        mock_conv.zalo_chat_id = "test_zalo_id"

        mock_sender = MagicMock()
        mock_sender.send_message = AsyncMock()
        mock_deps = MagicMock()
        mock_deps.zalo = MagicMock()
        mock_deps.zalo.for_conversation = MagicMock(return_value=mock_sender)

        mock_svc = MagicMock()
        mock_svc.get = AsyncMock(return_value=mock_conv)
        mock_svc.claim_send = AsyncMock(return_value=True)
        mock_svc.record_bot_outcome = AsyncMock()

        # Patch lazy imports at their SOURCE modules
        with patch("app.workers._db.worker_session", return_value=mock_db):
            with patch(
                "app.graph.factories.build_deps", new_callable=AsyncMock, return_value=mock_deps
            ):
                with patch("app.graph.runner.run_turn", new_callable=AsyncMock) as mock_run:
                    mock_run.side_effect = LLMThrottled("rate limit")
                    with patch("app.services.conversation.ConversationService") as MockSvc:
                        MockSvc.return_value = mock_svc
                        # Should NOT raise — LLMThrottled is caught
                        await _run_job_async(job)

        mock_sender.send_message.assert_not_called()
        mock_svc.claim_send.assert_not_called()
        mock_svc.record_bot_outcome.assert_called_once()
        kwargs = mock_svc.record_bot_outcome.call_args.kwargs
        assert kwargs["sent"] is False
        assert kwargs["reply"] == ""  # no customer text on the audit row either
        assert kwargs["stage_timings"]["throttle"] is True
        # The request-local decision trace is preserved for the dashboard.
        assert kwargs["decision_trace"] is not None

    @pytest.mark.asyncio
    async def test_worker_throttle_still_records_when_conversation_missing(self):
        """A vanished conversation must not crash the worker mid-recovery."""
        from app.workers.chatbot_worker import _run_job_async

        job = {
            "conversation_id": str(uuid.uuid4()),
            "version_at_start": 1,
            "user_text": "hello",
            "user_name": "Test",
        }

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_sender = MagicMock()
        mock_sender.send_message = AsyncMock()
        mock_deps = MagicMock()
        mock_deps.zalo = MagicMock()
        mock_deps.zalo.for_conversation = MagicMock(return_value=mock_sender)

        mock_svc = MagicMock()
        mock_svc.get = AsyncMock(return_value=None)  # conversation gone
        mock_svc.record_bot_outcome = AsyncMock()

        with patch("app.workers._db.worker_session", return_value=mock_db):
            with patch(
                "app.graph.factories.build_deps", new_callable=AsyncMock, return_value=mock_deps
            ):
                with patch("app.graph.runner.run_turn", new_callable=AsyncMock) as mock_run:
                    mock_run.side_effect = LLMThrottled("rate limit")
                    with patch("app.services.conversation.ConversationService") as MockSvc:
                        MockSvc.return_value = mock_svc
                        await _run_job_async(job)

        mock_svc.record_bot_outcome.assert_not_called()
        mock_sender.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_degradation_suppressed_when_not_owned(self):
        """A throttled turn that outlasted a recruiter takeover must not send.

        claim_send False → no send_message, record_bot_outcome(sent=False)
        so the outcome is SUPPRESSED (clears the mutex) and the recruiter-owned
        chat is not polluted with a degradation bubble.
        """
        from app.workers.chatbot_worker import _run_job_async

        job = {
            "conversation_id": str(uuid.uuid4()),
            "version_at_start": 1,
            "user_text": "hello",
            "user_name": "Test",
        }

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_conv = MagicMock()
        mock_conv.zalo_chat_id = "test_zalo_id"

        mock_sender = MagicMock()
        mock_sender.send_message = AsyncMock()
        mock_deps = MagicMock()
        mock_deps.zalo = MagicMock()
        mock_deps.zalo.for_conversation = MagicMock(return_value=mock_sender)

        mock_svc = MagicMock()
        mock_svc.get = AsyncMock(return_value=mock_conv)
        mock_svc.claim_send = AsyncMock(return_value=False)  # taken over
        mock_svc.record_bot_outcome = AsyncMock()

        with patch("app.workers._db.worker_session", return_value=mock_db):
            with patch(
                "app.graph.factories.build_deps", new_callable=AsyncMock, return_value=mock_deps
            ):
                with patch("app.graph.runner.run_turn", new_callable=AsyncMock) as mock_run:
                    mock_run.side_effect = LLMThrottled("rate limit")
                    with patch("app.services.conversation.ConversationService") as MockSvc:
                        MockSvc.return_value = mock_svc
                        await _run_job_async(job)

        mock_sender.send_message.assert_not_called()
        mock_svc.record_bot_outcome.assert_awaited_once()
        assert mock_svc.record_bot_outcome.call_args.kwargs["sent"] is False
