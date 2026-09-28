"""Redis-backed cross-process LLM concurrency semaphore.

RQ workers each run ``asyncio.run()`` per job — a fresh event loop every
turn.  An ``asyncio.Semaphore`` is therefore useless for cross-process
concurrency control.  Instead, we use Redis BLPOP/RPUSH on a token list:

* Startup (lazy): ``RPUSH <key> 1`` × N tokens.
* Acquire:   ``BLPOP <key> <timeout>`` — blocks until a token is free.
* Release:   ``RPUSH <key> 1`` in a ``finally`` block.
* Health:    ``LLEN <key>`` must equal N at rest; drift > 1 emits warning.
* Self-heal: an acquire recreates the token list if Redis evicted the key.

Two independent semaphores share the same ``RedisLlmSemaphore`` class with
different Redis keys:

- **LLM semaphore** (``llm_sem_tokens``) — guards MiniMax/OpenRouter calls.
- **Embed semaphore** (``llm_embed_sem_tokens``) — guards Gemini embed calls.

Both default to limit=0 which means disabled (pass-through).

Usage::

    from app.graph.llm_semaphore import get_llm_semaphore

    sem = get_llm_semaphore()
    async with sem:
        response = await bound.ainvoke(messages)
    # token automatically released, even on exception
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Literal

logger = logging.getLogger(__name__)


class LLMThrottled(Exception):
    """Raised when LLM 429 retry is exhausted — no LLM call should follow."""

    # Attached by the answer lane after the raise so the turn's decision trace
    # survives the throttle (the semaphore raise site has no trace sink).
    decision_trace: dict | None = None


# Release + excess prune in ONE atomic step: push the returned token, count,
# and trim anything above the limit. Doing this in three round trips allowed
# a racing release/eviction-recreate to prune tokens another release had
# already counted, permanently shrinking the cap below the limit; inside a
# script Redis executes the block without interleaving.
_RELEASE_TOKEN_LUA = """\
redis.call('RPUSH', KEYS[1], 1)
local n = redis.call('LLEN', KEYS[1])
local excess = n - tonumber(ARGV[1])
if excess > 0 then
  for _ = 1, excess do
    redis.call('RPOP', KEYS[1])
  end
  n = tonumber(ARGV[1])
end
return n
"""


class RedisLlmSemaphore:
    """Cross-process concurrency guard backed by a Redis token list."""

    def __init__(
        self,
        limit: int = 0,
        *,
        key: str = "llm_sem_tokens",
        acquire_timeout: float = 1.5,
    ) -> None:
        self._limit = limit  # 0 = disabled (pass-through)
        self._key = key
        self._acquire_timeout = acquire_timeout  # BLPOP wait before fail-fast
        self._initialized = False
        self._acquired = False  # tracks whether __aenter__ got a token

    def _ensure_tokens(self) -> None:
        """Populate the token list on first use; recreate it if Redis lost it.

        ``allkeys-lru`` treats the token list like any other key: once evicted
        with no in-flight holders, the list never regrows and every BLPOP
        times out until process restart — a deployment-wide LLM outage. The
        once-per-process registration is kept as the fast path; afterwards
        every acquire pays one cheap EXISTS and recreates the list when it is
        missing. A present-but-short list is NOT topped up: that shortage is
        tokens legitimately checked out under load, and refilling then would
        inflate the concurrency cap exactly when it must hold.

        Blocking sync-client commands: ``__aenter__`` runs this on a worker
        thread (REL-02), never inline on the event loop.
        """
        if self._limit <= 0:
            return
        try:
            from app.core.redis import get_redis_sync, sync_value

            r = get_redis_sync()
            if not self._initialized:
                current = sync_value(r.llen(self._key))
                if current < self._limit:
                    r.rpush(self._key, *[1] * (self._limit - current))
                # Token keys carry no TTL: the deployment's volatile-lru
                # policy only ever evicts TTL'd keys, so PERSIST keeps the
                # token list out of the eviction blast radius even if
                # something else set a TTL on it.
                r.persist(self._key)
                self._initialized = True
                logger.info(
                    "llm_semaphore initialized",
                    extra={
                        "key": self._key,
                        "limit": self._limit,
                        "tokens_added": self._limit - current,
                    },
                )
            elif not r.exists(self._key):
                r.rpush(self._key, *[1] * self._limit)
                r.persist(self._key)
                logger.warning(
                    "llm_semaphore token list recreated after eviction",
                    extra={"key": self._key, "limit": self._limit},
                )
        except Exception:  # noqa: BLE001
            logger.warning(
                "failed to ensure semaphore tokens for key=%s", self._key, exc_info=True
            )

    def _release_token(self) -> None:
        """Push the token back and prune any excess. Blocking; call off the loop.

        The async client is deliberately NOT used for the token list: the list
        BLPOP reads must be the same store the bookkeeping writes, and this client
        is shared with the acquire path (RQ workers run a fresh event loop per
        job). ``__aexit__`` therefore dispatches this to a worker thread.
        """
        try:
            from app.core.redis import get_redis_sync, sync_value

            r = get_redis_sync()
            count = int(sync_value(r.eval(_RELEASE_TOKEN_LUA, 1, self._key, self._limit)) or 0)
            # The script trims excess above the limit atomically, so the
            # count can only sit at or below the limit afterwards; a
            # shortfall reflects tokens legitimately held in flight (or a
            # genuine leak, which the drift warning still surfaces).
            delta = count - self._limit
            if abs(delta) > 1:
                logger.warning(
                    "llm_semaphore token drift",
                    extra={
                        "key": self._key,
                        "expected": self._limit,
                        "actual": count,
                        "delta": delta,
                    },
                )
            if delta > 0:
                for _ in range(delta):
                    r.rpop(self._key)
        except Exception:  # noqa: BLE001
            pass  # release must be best-effort

    async def __aenter__(self) -> "RedisLlmSemaphore":
        """Acquire a token (blocking with timeout)."""
        if self._limit <= 0:
            self._acquired = False
            return self
        # Every command this class issues is a blocking sync-client call, so all
        # of them run on a worker thread: the token bookkeeping here and the BLPOP
        # below (REL-02).
        await asyncio.to_thread(self._ensure_tokens)
        try:
            from app.core.redis import get_redis_sync

            r = get_redis_sync()
            # BLPOP blocks up to the acquire timeout. On timeout we fail FAST
            # (raise LLMThrottled) rather than proceeding degraded: the worker
            # already suppresses the turn + clears the per-chat mutex on
            # LLMThrottled, and a degraded parallel call would only compound the
            # overload that caused the timeout.
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: r.blpop(self._key, timeout=self._acquire_timeout)
            )
        except Exception:  # noqa: BLE001 — Redis unavailable: degrade, don't hard-fail
            self._acquired = False
            logger.warning(
                "llm_semaphore: acquire errored — proceeding without token", exc_info=True
            )
            return self
        if result is None:
            self._acquired = False
            logger.warning(
                "llm_semaphore: acquire timed out — raising LLMThrottled (fail fast)",
                extra={"key": self._key, "timeout": self._acquire_timeout},
            )
            raise LLMThrottled("llm_semaphore: acquire timed out")
        self._acquired = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Release the token back to the pool (off the event loop).

        ``Literal[False]`` is load-bearing, not decoration: it tells the type
        checker that the guard never swallows an exception, so a value bound
        inside ``async with get_llm_semaphore():`` is known to be bound after
        the block. A plain ``bool`` return makes every such block look like it
        might be skipped, which is what turned each one into a false
        "possibly unbound".
        """
        if self._limit > 0 and self._acquired:
            await asyncio.to_thread(self._release_token)
        self._acquired = False
        return False


# ── Module-level singletons (lazily created on first use) ────────────────────

_sem: RedisLlmSemaphore | None = None
_embed_sem: RedisLlmSemaphore | None = None


def get_llm_semaphore() -> RedisLlmSemaphore:
    """Return (and lazily create) the module-level Redis LLM semaphore."""
    global _sem
    if _sem is None:
        from app.core.config import get_settings

        s = get_settings()
        _sem = RedisLlmSemaphore(
            limit=s.llm_concurrency_limit,
            key="llm_sem_tokens",
            acquire_timeout=s.llm_acquire_timeout_seconds,
        )
    return _sem


def get_embed_semaphore() -> RedisLlmSemaphore:
    """Return (and lazily create) the embed semaphore (separate Redis key)."""
    global _embed_sem
    if _embed_sem is None:
        from app.core.config import get_settings

        s = get_settings()
        _embed_sem = RedisLlmSemaphore(
            limit=s.embed_concurrency_limit,
            key="llm_embed_sem_tokens",
            acquire_timeout=s.llm_acquire_timeout_seconds,
        )
    return _embed_sem
