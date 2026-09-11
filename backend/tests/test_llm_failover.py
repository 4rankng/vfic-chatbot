"""Cross-provider failover when a provider runs out of capacity.

A spent token plan must not reach the candidate as an error: the turn walks the
other configured providers, and only a fully exhausted chain degrades to the
static reply.
"""

from __future__ import annotations

import pytest

from app.graph.clients import _is_quota_exhausted, _llm_call_with_retry
from app.graph.llm_semaphore import LLMThrottled


class _Boom:
    """A provider that always fails with the given message."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ARG002
        self.calls += 1
        raise RuntimeError(self.message)


class _Ok:
    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ARG002
        self.calls += 1
        return self.reply


@pytest.mark.parametrize(
    "message",
    [
        "insufficient balance",
        "Error code: 402 - payment required",
        "You exceeded your current quota",
        "insufficient_quota",
    ],
)
def test_quota_messages_are_recognised(message):
    assert _is_quota_exhausted(RuntimeError(message)) is True


@pytest.mark.parametrize("message", ["429 Too Many Requests", "timeout", "bad gateway"])
def test_non_quota_messages_are_not_quota(message):
    assert _is_quota_exhausted(RuntimeError(message)) is False


async def test_quota_exhaustion_fails_over_without_backoff():
    """A spent plan does not recover by waiting, so no backoff is spent on it."""
    primary = _Boom("insufficient balance")
    spare = _Ok("từ nhà cung cấp dự phòng")
    metrics: dict = {}

    result, backoff_ms = await _llm_call_with_retry(
        primary, ["m"], metrics=metrics, fallback_bounds=[spare]
    )

    assert result == "từ nhà cung cấp dự phòng"
    assert backoff_ms == 0
    assert primary.calls == 1  # no pointless retry against a spent plan
    assert spare.calls == 1
    assert metrics["llm_failover"] is True
    assert metrics["llm_failover_reason"] == "quota_exhausted"


async def test_failover_walks_past_a_spare_that_is_also_exhausted():
    """One spent spare must not strand the turn."""
    primary = _Boom("insufficient balance")
    dead_spare = _Boom("insufficient balance")
    live_spare = _Ok()
    metrics: dict = {}

    result, _ = await _llm_call_with_retry(
        primary, ["m"], metrics=metrics, fallback_bounds=[dead_spare, live_spare]
    )

    assert result == "ok"
    assert dead_spare.calls == 1
    assert live_spare.calls == 1
    assert metrics["llm_failover_index"] == 2


async def test_all_providers_exhausted_degrades_instead_of_leaking_the_error():
    """The candidate gets the static degradation reply, never a provider error."""
    primary = _Boom("insufficient balance")

    with pytest.raises(LLMThrottled):
        await _llm_call_with_retry(
            primary, ["m"], fallback_bounds=[_Boom("insufficient balance")]
        )


async def test_no_failover_configured_still_raises_throttled():
    primary = _Boom("insufficient balance")

    with pytest.raises(LLMThrottled):
        await _llm_call_with_retry(primary, ["m"], fallback_bounds=[])


async def test_healthy_primary_never_touches_the_spare():
    primary = _Ok("primary")
    spare = _Ok("spare")

    result, backoff_ms = await _llm_call_with_retry(primary, ["m"], fallback_bounds=[spare])

    assert result == "primary"
    assert backoff_ms == 0
    assert spare.calls == 0
