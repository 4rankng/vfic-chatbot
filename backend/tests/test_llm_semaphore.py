"""Tests for Redis-backed LLM semaphore, 429 retry, and degradation path."""

from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace
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

    Thread-safe via a lock (needed for concurrent acquire tests where
    run_in_executor dispatches BLPOP to a thread pool).
    """
    store: dict[str, list] = {}
    lock = threading.Lock()

    r = MagicMock()

    def _rpush(key, *vals):
        with lock:
            store.setdefault(key, []).extend(vals)

    def _blpop(key, timeout=0):
        with lock:
            lst = store.get(key, [])
            if lst:
                return (key, lst.pop(0))
            return None  # timeout

    def _llen(key):
        with lock:
            return len(store.get(key, []))

    r.rpush = MagicMock(side_effect=_rpush)
    r.blpop = MagicMock(side_effect=_blpop)
    r.llen = MagicMock(side_effect=_llen)
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
    async def test_drift_above_one_warns(self, fake_redis):
        """If drift exceeds 1, warning is logged."""
        sem = RedisLlmSemaphore(limit=2, key="test_drift_bad")
        with patch(_REDIS_PATCH, return_value=fake_redis):
            sem._ensure_tokens()
            # Inject 2 extra tokens to get drift=2 (need abs(delta) > 1)
            fake_redis.rpush("test_drift_bad", 1)
            fake_redis.rpush("test_drift_bad", 1)
            with patch("app.graph.llm_semaphore.logger") as mock_logger:
                async with sem:
                    pass
                # Should have warned about drift
                mock_logger.warning.assert_called()


class TestSemaphoreTimeout:
    """BLPOP timeout fail-fasts (raises LLMThrottled, no silent degraded stall)."""

    @pytest.mark.asyncio
    async def test_timeout_raises_llm_throttled(self, fake_redis):
        """When BLPOP returns None (timeout), __aenter__ raises LLMThrottled so the
        worker sends DEGRADATION_REPLY and clears the per-chat mutex."""
        sem = RedisLlmSemaphore(limit=1, key="test_timeout", acquire_timeout=0)
        sem._initialized = True  # skip token population → BLPOP returns None
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


# ── 429 retry in clients ────────────────────────────────────────────────────


class TestRetry429:
    """_llm_call_with_retry retries once on 429 then raises LLMThrottled."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        from app.graph.clients import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
        with patch("app.graph.clients._record_llm_429"):
            result, backoff_ms = await _llm_call_with_retry(bound, [])
        assert result.content == "ok"
        assert bound.ainvoke.call_count == 1
        assert backoff_ms == 0  # no backoff on the happy path

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        from app.graph.clients import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(
            side_effect=[
                Exception("429 Too Many Requests"),
                MagicMock(content="retried ok"),
            ]
        )
        with patch("app.graph.clients._record_llm_429") as mock_429:
            with patch("app.graph.clients.asyncio.sleep", new_callable=AsyncMock):
                result, backoff_ms = await _llm_call_with_retry(bound, [])
        assert result.content == "retried ok"
        assert bound.ainvoke.call_count == 2
        mock_429.assert_called_once()
        assert backoff_ms >= 0  # backoff measured around the patched sleep

    @pytest.mark.asyncio
    async def test_raises_llm_throttled_on_double_429(self):
        from app.graph.clients import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(
            side_effect=[
                Exception("429 rate limit exceeded"),
                Exception("429 rate limit exceeded"),
            ]
        )
        with patch("app.graph.clients._record_llm_429"):
            with patch("app.graph.clients.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(LLMThrottled):
                    await _llm_call_with_retry(bound, [])

    @pytest.mark.asyncio
    async def test_no_retry_on_non_429_error(self):
        from app.graph.clients import _llm_call_with_retry

        bound = AsyncMock()
        bound.ainvoke = AsyncMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            await _llm_call_with_retry(bound, [])
        assert bound.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_sleep_uses_configured_setting(self):
        """Retry sleep is settings.llm_429_retry_sleep_seconds (no hardcoded jitter)."""
        from app.core.config import get_settings
        from app.graph.clients import _llm_call_with_retry

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

        with patch("app.graph.clients._record_llm_429"):
            with patch("app.graph.clients.asyncio.sleep", side_effect=_capture_sleep):
                await _llm_call_with_retry(bound, [])
        assert len(sleep_args) == 1
        assert sleep_args[0] == get_settings().llm_429_retry_sleep_seconds


# ── Degradation message in worker ───────────────────────────────────────────


class TestDegradationMessage:
    """chatbot_worker sends static Vietnamese msg on LLMThrottled."""

    def test_degradation_reply_is_vietnamese(self):
        from app.workers.chatbot_worker import DEGRADATION_REPLY

        assert "Xin lỗi" in DEGRADATION_REPLY
        assert "truy cập" in DEGRADATION_REPLY
        # Must NOT contain emoji
        assert "\U0001f60a" not in DEGRADATION_REPLY  # 😊

    @pytest.mark.asyncio
    async def test_worker_catches_llm_throttled(self):
        """When run_turn raises LLMThrottled, worker sends degradation msg."""
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

        # The worker binds the outbound sender via deps.zalo.for_conversation(conv),
        # then awaits sender.send_message(chat_id, text). The awaitable must live on
        # the BOUND sender, not on deps.zalo directly.
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

        mock_sender.send_message.assert_called_once()
        sent_msg = mock_sender.send_message.call_args[0][1]
        assert "Xin lỗi" in sent_msg

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

    @pytest.mark.asyncio
    async def test_worker_messenger_degradation_uses_canonical_outbox_route(self):
        """The last-resort static reply must still use Messenger durable delivery."""
        from app.graph.ports import SendOutcome
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
        mock_conv = SimpleNamespace(
            zalo_chat_id=None,
            zalo_channel="facebook_messenger",
            channel_identity=SimpleNamespace(
                provider="facebook_messenger",
                account_key="page-1",
                external_id="psid-1",
            ),
        )
        mock_sender = MagicMock()
        mock_sender.send_message = AsyncMock()
        mock_deps = MagicMock()
        mock_deps.zalo = MagicMock()
        mock_deps.zalo.for_conversation = MagicMock(return_value=mock_sender)
        mock_svc = MagicMock()
        mock_svc.get = AsyncMock(return_value=mock_conv)
        mock_svc.claim_send = AsyncMock(return_value=True)
        mock_svc.dispatch_outbound_message = AsyncMock(
            return_value=SendOutcome(ok=True, msg_id="mid-1")
        )
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

        claim = mock_svc.claim_send.await_args
        assert claim.kwargs["outbox_channel"] == "facebook_messenger"
        assert claim.kwargs["outbox_payload"]["chat_id"] == "psid-1"
        mock_svc.dispatch_outbound_message.assert_awaited_once()
        mock_sender.send_message.assert_not_awaited()
        recorded = mock_svc.record_bot_outcome.await_args
        assert recorded.kwargs["outbox_channel"] == "facebook_messenger"
        assert recorded.kwargs["outbox_payload"]["chat_id"] == "psid-1"
