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
import re
import time
from typing import TYPE_CHECKING

from app.graph.llm_observability import _record_llm_429

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)

# Rate-limit detection. The previous check was `"rate" in str(exc).lower()`,
# which also matched unrelated words ("moderate", "corporate", "generate rate")
# and turned an ordinary provider error into a 0.5 s backoff + pointless retry +
# a false increment of the `minimax_429s` tile. Match the status code or an
# explicit rate-limit phrase instead.
_RATE_LIMIT_RE = re.compile(r"\b429\b")
_RATE_LIMIT_PHRASES = ("rate limit", "rate_limit", "ratelimit", "too many requests")


def _is_429(exc: Exception) -> bool:
    """Check if an exception represents an HTTP 429 (rate limit)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status == 429
    text = str(exc).lower()
    return bool(_RATE_LIMIT_RE.search(text)) or any(p in text for p in _RATE_LIMIT_PHRASES)


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
    bound: Runnable,
    messages,
    *,
    metrics: dict | None = None,
    fallback_bounds: list | None = None,
) -> tuple[AIMessage, int]:
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


def _content_text(chunk: object) -> str:
    """Best-effort plain text from a streamed chunk's ``content``."""
    content = getattr(chunk, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


async def _stream_collect(bound, messages, on_delta) -> AIMessage:
    """Stream one completion, forwarding text deltas, and return the merged message.

    langchain's ``AIMessageChunk`` supports ``+``, so summing the chunks yields a
    message with the same ``content`` / ``tool_calls`` / ``usage_metadata`` shape
    the non-streaming path returns — the agent loop above needs no special case.
    A tool-request round simply yields no text deltas (measured: providers emit no
    visible content alongside ``tool_calls``), so nothing is sent for it.
    """
    from langchain_core.messages import AIMessageChunk

    assembled: AIMessageChunk | None = None
    async for chunk in bound.astream(messages):
        assembled = chunk if assembled is None else assembled + chunk
        if on_delta is not None:
            text = _content_text(chunk)
            if text:
                await on_delta(text)
    if assembled is None:
        return AIMessageChunk(content="")
    return assembled


class _OverlapSuppressor:
    """Drops a replacement attempt's re-emission of text already handed over.

    A mid-stream capacity failure makes the next attempt re-run the WHOLE
    completion from the same messages, so it re-emits the prefix the dead
    provider already produced. Text that reached ``on_delta`` cannot be
    recalled, so forwarding the re-emission would show the candidate the same
    opening content twice.

    The comparison is against the CONCATENATED emitted text, never per chunk: a
    provider's chunk boundaries have nothing to do with the boundaries of the
    attempt that failed, so the replacement's first chunk is typically only a
    partial repeat of the last chunk emitted before the failure. Feeding chunk
    by chunk and asking "does this chunk repeat what came before" misses exactly
    that case and duplicates text.

    The rule is all-or-nothing: the replacement's text is dropped only when it
    genuinely RE-EMITS the delivered prefix (it starts with it, verbatim). When
    it is a different answer, nothing is dropped — cutting at the point where
    the two texts happen to diverge would splice one answer onto the other and
    ship nonsense. Nothing is forwarded until the replacement has produced at
    least ``len(target)`` characters, because only then is the question
    decidable; a replacement that ends before that point is a shorter, different
    answer and is forwarded whole.
    """

    def __init__(self, target: str) -> None:
        self._target = target
        self._buffer = ""
        self._resolved = False
        self.suppressed = 0

    def _resolve(self) -> str:
        if self._buffer.startswith(self._target):
            self.suppressed = len(self._target)
        self._resolved = True
        remainder = self._buffer[self.suppressed :]
        self._buffer = ""
        return remainder

    def feed(self, text: str) -> str:
        """Buffer ``text`` and return whatever of it is genuinely new."""
        if self._resolved:
            return text
        self._buffer += text
        if len(self._buffer) < len(self._target):
            return ""
        return self._resolve()

    def flush(self) -> str:
        """Release whatever the replacement produced, minus any re-emission."""
        if self._resolved:
            return ""
        return self._resolve()


async def _llm_call_streaming_with_retry(
    bound: Runnable,
    messages,
    *,
    on_delta,
    metrics: dict | None = None,
    fallback_bounds: list | None = None,
) -> tuple[AIMessage, int]:
    """Streaming twin of :func:`_llm_call_with_retry`.

    Same capacity policy as :func:`_llm_call_with_retry` — retry once on 429,
    fail over on a spent plan or a second 429, re-raise anything else — with one
    honest difference: text already handed to ``on_delta`` cannot be recalled. A
    capacity failure *before* the first token is therefore still a clean
    retry/failover, while a capacity failure mid-stream sets ``stream_partial``
    before the walk continues: the same partially-delivered state the chunked
    sender already tolerates for a multi-bubble answer. A non-capacity failure
    mid-stream still propagates (unchanged contract) and the turn degrades.

    Any attempt that starts after text was already emitted suppresses the
    re-emission of that text (:class:`_OverlapSuppressor`), so the candidate
    reads the answer once. The merged message still carries the replacement's
    FULL text, which is what the agent loop returns as the turn's answer.
    Returns ``(merged_message, backoff_ms)``.
    """
    from app.core.config import get_settings
    from app.graph.llm_semaphore import LLMThrottled

    # Every fragment handed to ``on_delta`` on this call, concatenated. Once
    # non-empty the candidate has seen a prefix that no later attempt can
    # recall, so the turn is partial no matter which provider finishes it.
    emitted: list[str] = []

    async def _attempt(client, *, suppress_overlap: bool = False) -> AIMessage:
        suppressor = _OverlapSuppressor("".join(emitted)) if suppress_overlap else None

        if suppressor is None:

            async def _tap(text: str) -> None:
                emitted.append(text)
                await on_delta(text)

        else:

            async def _tap(text: str) -> None:
                fresh = suppressor.feed(text)
                if fresh:
                    emitted.append(fresh)
                    await on_delta(fresh)

        merged = await _stream_collect(client, messages, _tap)
        if suppressor is not None:
            tail = suppressor.flush()
            if tail:
                emitted.append(tail)
                await on_delta(tail)
            if suppressor.suppressed and metrics is not None:
                metrics["stream_overlap_suppressed"] = suppressor.suppressed
        return merged

    async def _failover_stream(reason: str, backoff_ms: int):
        candidates = [client for client in (fallback_bounds or []) if client is not None]
        if not candidates:
            raise LLMThrottled(f"LLM unavailable ({reason}) and no failover provider configured")
        # Frozen once: whether the turn was already partial when the failover
        # began. The overlap decision below is re-made per attempt, because a
        # replacement that itself dies mid-stream leaves the NEXT one with
        # something new to suppress.
        partial = bool(emitted)
        for index, client in enumerate(candidates):
            try:
                result = await _attempt(client, suppress_overlap=bool(emitted))
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
                if partial:
                    metrics["stream_partial"] = True
            return result, backoff_ms
        raise LLMThrottled(f"LLM unavailable ({reason}); all failover providers exhausted")

    try:
        return await _attempt(bound), 0
    except Exception as exc:
        if _is_quota_exhausted(exc):
            return await _failover_stream("quota_exhausted", 0)
        if _is_429(exc):
            await _record_llm_429()
            logger.warning("llm_429_retry", exc_info=True)
            backoff_t0 = time.monotonic()
            await asyncio.sleep(get_settings().llm_429_retry_sleep_seconds)
            backoff_ms = int((time.monotonic() - backoff_t0) * 1000)
            if metrics is not None:
                metrics["retried_429"] = True
            try:
                return await _attempt(bound, suppress_overlap=bool(emitted)), backoff_ms
            except Exception as exc2:
                if _is_quota_exhausted(exc2):
                    return await _failover_stream("quota_exhausted", backoff_ms)
                if _is_429(exc2):
                    await _record_llm_429()
                    return await _failover_stream("rate_limited", backoff_ms)
                raise
        raise
