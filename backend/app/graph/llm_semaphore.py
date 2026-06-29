"""Redis-backed cross-process LLM concurrency semaphore.

RQ workers each run ``asyncio.run()`` per job — a fresh event loop every
turn.  An ``asyncio.Semaphore`` is therefore useless for cross-process
concurrency control.  Instead, we use Redis BLPOP/RPUSH on a token list:

* Startup (lazy): ``RPUSH <key> 1`` × N tokens.
* Acquire:   ``BLPOP <key> <timeout>`` — blocks until a token is free.
* Release:   ``RPUSH <key> 1`` in a ``finally`` block.
* Health:    ``LLEN <key>`` must equal N at rest; drift > 1 emits warning.

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

logger = logging.getLogger(__name__)


class LLMThrottled(Exception):
    """Raised when LLM 429 retry is exhausted — no LLM call should follow."""
    pass


class RedisLlmSemaphore:
    """Cross-process concurrency guard backed by a Redis token list."""

    def __init__(self, limit: int = 0, *, key: str = "llm_sem_tokens") -> None:
        self._limit = limit  # 0 = disabled (pass-through)
        self._key = key
        self._initialized = False
        self._acquired = False  # tracks whether __aenter__ got a token

    def _ensure_tokens(self) -> None:
        """Lazily populate the token list (idempotent — safe to call multiple times)."""
        if self._limit <= 0 or self._initialized:
            return
        try:
            from app.core.redis import get_redis_sync

            r = get_redis_sync()
            current = r.llen(self._key)
            if current < self._limit:
                r.rpush(self._key, *[1] * (self._limit - current))
            self._initialized = True
            logger.info(
                "llm_semaphore initialized",
                extra={"key": self._key, "limit": self._limit, "tokens_added": self._limit - current},
            )
        except Exception:  # noqa: BLE001
            logger.warning("failed to initialize semaphore tokens for key=%s", self._key, exc_info=True)

    async def __aenter__(self) -> "RedisLlmSemaphore":
        """Acquire a token (blocking with timeout)."""
        if self._limit <= 0:
            self._acquired = False
            return self
        self._ensure_tokens()
        try:
            from app.core.redis import get_redis_sync

            r = get_redis_sync()
            # BLPOP blocks up to timeout. Timeout is per-turn (not per-wait):
            # if the turn can't get a slot, it still proceeds (degraded mode).
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: r.blpop(self._key, timeout=30)
            )
            if result is None:
                logger.warning(
                    "llm_semaphore: acquire timed out — proceeding without token",
                    extra={"key": self._key},
                )
            self._acquired = True
        except Exception:  # noqa: BLE001
            self._acquired = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Release the token back to the pool."""
        if self._limit > 0 and self._acquired:
            try:
                from app.core.redis import get_redis_sync

                r = get_redis_sync()
                r.rpush(self._key, 1)
                # Drift detection: LLEN should equal limit at rest.
                count = r.llen(self._key)
                delta = count - self._limit
                if abs(delta) > 1:
                    logger.warning(
                        "llm_semaphore token drift",
                        extra={"key": self._key, "expected": self._limit, "actual": count, "delta": delta},
                    )
            except Exception:  # noqa: BLE001
                pass  # release must be best-effort
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
        _sem = RedisLlmSemaphore(limit=s.llm_concurrency_limit, key="llm_sem_tokens")
    return _sem


def get_embed_semaphore() -> RedisLlmSemaphore:
    """Return (and lazily create) the embed semaphore (separate Redis key)."""
    global _embed_sem
    if _embed_sem is None:
        from app.core.config import get_settings

        s = get_settings()
        _embed_sem = RedisLlmSemaphore(limit=s.embed_concurrency_limit, key="llm_embed_sem_tokens")
    return _embed_sem
