"""Provider rate-limit retry and cross-provider quota failover.

One LLM call is attempted on the turn's provider; a 429 gets a single backoff
retry, a spent plan (quota) and a second 429 walk the remaining configured
providers in order. Only a fully exhausted chain raises ``LLMThrottled``, which
the worker turns into the static degradation reply — a candidate never sees a
provider error. Redis counters for the 429 path live in
``graph/llm_observability.py``.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.graph.llm_observability import _record_llm_429

logger = logging.getLogger(__name__)


def _is_429(exc: Exception) -> bool:
    """Check if an exception represents an HTTP 429 (rate limit)."""
    return "429" in str(exc) or "rate" in str(exc).lower()


# Quota exhaustion is not a rate limit: a spent token plan does not recover by
# waiting, so retrying the same provider only burns the turn deadline. Providers
# signal it out-of-band from 429 (MiniMax returns "insufficient balance", others
# use 402 / "quota"), hence a separate predicate that routes straight to the
# failover provider instead of through the backoff path.
_QUOTA_MARKERS = (
    "insufficient balance",
    "insufficient_quota",
    "insufficient credit",
    "quota exceeded",
    "quota_exceeded",
    "exceeded your current quota",
    "out of credits",
    "payment required",
    "402",
)


def _is_quota_exhausted(exc: Exception) -> bool:
    """True when the provider says the plan is spent, not merely throttled."""
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_MARKERS)


def _bind_like(llm, schemas, *, bound_primary: bool):
    """Mirror the primary's tool binding onto the failover client.

    A failover mid-loop must expose the same tools, otherwise the model loses
    the capability the conversation is already relying on. Returns ``None`` when
    no failover provider is configured, which disables failover for that call.
    """
    if llm is None:
        return None
    if not bound_primary or not schemas:
        return llm
    bind_tools = getattr(llm, "bind_tools", None)
    if bind_tools is None:
        return llm
    try:
        return bind_tools(schemas)
    except Exception:  # noqa: BLE001 — an unbindable failover is better than none
        logger.warning("failover client could not bind tools; using it unbound", exc_info=True)
        return llm


async def _llm_call_with_retry(
    bound,
    messages,
    *,
    metrics: dict | None = None,
    fallback_bounds: list | None = None,
):
    """Call bound.ainvoke with 1 retry on 429 (settings.llm_429_retry_sleep_seconds backoff).

    ``fallback_bounds`` (optional) is an ordered list of equivalently-bound
    clients on the OTHER configured providers — every provider the operator has
    enabled with a usable credential, not one designated spare. They are tried
    in order when the primary is out of capacity:

    * quota exhausted — the plan is spent and will not recover by waiting, so
      the next provider runs immediately with no backoff sleep;
    * rate limited twice — one backoff retry first, then the next provider.

    A provider that is itself out of capacity is skipped and the walk continues,
    so one spent plan does not strand the turn. Only when every provider is
    exhausted does this raise LLMThrottled, and the worker then sends the static
    degradation reply — a candidate never sees a provider error.

    When ``metrics`` is provided, sets ``retried_429`` on the backoff path and
    ``llm_failover`` / ``llm_failover_reason`` / ``llm_failover_index`` when the
    reply came from a failover provider, so a turn that silently changed
    provider is visible in the turn record.

    Returns ``(result, backoff_ms)`` where ``backoff_ms`` is the wall-clock time
    spent sleeping during a rate-limit backoff (0 on the happy path). The caller
    uses this to exclude the sleep from ``llm_model_ms`` so the split stays
    clean — model inference never includes the 429 backoff.
    """
    from app.core.config import get_settings
    from app.graph.llm_semaphore import LLMThrottled

    async def _failover(reason: str, backoff_ms: int):
        """Walk the remaining providers in order until one answers."""
        candidates = [client for client in (fallback_bounds or []) if client is not None]
        if not candidates:
            raise LLMThrottled(f"LLM unavailable ({reason}) and no failover provider configured")
        for index, client in enumerate(candidates):
            try:
                result = await client.ainvoke(messages)
            except Exception:  # noqa: BLE001 — try the next provider, whatever failed
                logger.warning(
                    "llm_failover provider %d/%d failed; trying next",
                    index + 1,
                    len(candidates),
                    exc_info=True,
                )
                continue
            logger.warning(
                "llm_failover_engaged reason=%s provider_index=%d", reason, index + 1
            )
            if metrics is not None:
                metrics["llm_failover"] = True
                metrics["llm_failover_reason"] = reason
                metrics["llm_failover_index"] = index + 1
            return result, backoff_ms
        raise LLMThrottled(f"LLM unavailable ({reason}); all failover providers exhausted")

    try:
        return await bound.ainvoke(messages), 0
    except Exception as exc:
        # A spent plan does not recover by sleeping — skip the backoff entirely.
        if _is_quota_exhausted(exc):
            return await _failover("quota_exhausted", 0)
        if _is_429(exc):
            await _record_llm_429()
            logger.warning("llm_429_retry", exc_info=True)
            backoff_t0 = time.monotonic()
            await asyncio.sleep(get_settings().llm_429_retry_sleep_seconds)
            backoff_ms = int((time.monotonic() - backoff_t0) * 1000)
            if metrics is not None:
                metrics["retried_429"] = True
            try:
                return await bound.ainvoke(messages), backoff_ms
            except Exception as exc2:
                if _is_quota_exhausted(exc2):
                    return await _failover("quota_exhausted", backoff_ms)
                if _is_429(exc2):
                    await _record_llm_429()
                    return await _failover("rate_limited", backoff_ms)
                raise
        raise
