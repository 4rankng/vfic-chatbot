"""Cross-provider failover when a provider runs out of capacity.

A spent token plan must not reach the candidate as an error: the turn walks the
other configured providers, and only a fully exhausted chain suppresses the
turn (nothing is sent to the candidate — the failure goes to the logs).
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


# ── Failover-chain construction (factories) ─────────────────────────────────


class _RecordingBuilders:
    """Stub the three provider builders so no real client is constructed."""

    def __init__(self, monkeypatch):
        from app.graph import factories

        self.built: list[str] = []
        monkeypatch.setattr(
            factories,
            "_minimax_chat",
            lambda model, *, temperature, api_key, **_: self.built.append(
                f"minimax:{model}"
            )
            or object(),
        )
        monkeypatch.setattr(
            factories,
            "_openrouter_chat",
            lambda model, *, temperature, **_: self.built.append(
                f"openrouter:{model}"
            )
            or object(),
        )
        monkeypatch.setattr(
            factories,
            "_custom_chat",
            lambda model, *, temperature, api_key, base_url, **_: self.built.append(
                f"custom:{model}"
            )
            or object(),
        )


def _configs(default_provider: str):
    from app.services.integration_settings import (
        CustomLlmRuntimeConfig,
        MinimaxRuntimeConfig,
        OpenRouterRuntimeConfig,
    )

    minimax = MinimaxRuntimeConfig(
        enabled=True, api_key="mm-key", agent_model="mm-agent", default_provider=default_provider
    )
    openrouter = OpenRouterRuntimeConfig(
        enabled=True,
        api_key="or-key",
        agent_model="or-agent",
        default_provider=default_provider,
    )
    custom = CustomLlmRuntimeConfig(
        enabled=True,
        api_key="cu-key",
        base_url="https://custom.example/v1",
        agent_model="cu-agent",
        default_provider=default_provider,
    )
    return minimax, openrouter, custom


def test_failover_chain_excludes_the_active_provider(monkeypatch):
    """The active provider must never be its own spare: retrying a quota-dead
    provider against itself burns the turn deadline for nothing."""
    from app.graph.factories import _build_failover_chain

    rec = _RecordingBuilders(monkeypatch)
    minimax, openrouter, custom = _configs(default_provider="custom")

    chain = _build_failover_chain(
        minimax_config=minimax,
        openrouter_config=openrouter,
        custom_config=custom,
    )

    assert len(chain) == 2
    assert rec.built == ["minimax:mm-agent", "openrouter:or-agent"]


def test_failover_chain_walks_the_other_providers_in_deterministic_order(monkeypatch):
    from app.graph.factories import _build_failover_chain

    rec = _RecordingBuilders(monkeypatch)
    minimax, openrouter, custom = _configs(default_provider="minimax")

    _build_failover_chain(
        minimax_config=minimax,
        openrouter_config=openrouter,
        custom_config=custom,
    )

    assert rec.built == ["openrouter:or-agent", "custom:cu-agent"]
def test_failover_chain_skips_a_disabled_spare(monkeypatch):
    """A spare without enabled+credential must not join the chain."""
    from app.graph.factories import _build_failover_chain
    from app.services.integration_settings import (
        CustomLlmRuntimeConfig,
        MinimaxRuntimeConfig,
        OpenRouterRuntimeConfig,
    )

    rec = _RecordingBuilders(monkeypatch)

    _build_failover_chain(
        minimax_config=MinimaxRuntimeConfig(
            enabled=True, api_key="mm-key", agent_model="mm-agent", default_provider="minimax"
        ),
        openrouter_config=OpenRouterRuntimeConfig(
            enabled=False, api_key="", agent_model="or-agent", default_provider="minimax"
        ),
        custom_config=CustomLlmRuntimeConfig(
            enabled=True,
            api_key="cu-key",
            base_url="https://custom.example/v1",
            agent_model="cu-agent",
            default_provider="minimax",
        ),
    )

    assert rec.built == ["custom:cu-agent"]
