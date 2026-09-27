"""Cross-provider failover when a provider runs out of capacity.

A spent token plan must not reach the candidate as an error: the turn walks the
other configured providers, and only a fully exhausted chain suppresses the
turn (nothing is sent to the candidate — the failure goes to the logs).
"""

from __future__ import annotations

import pytest

from app.graph.llm_semaphore import LLMThrottled
from app.graph.provider_failover import (
    _is_429,
    _is_quota_exhausted,
    _llm_call_streaming_with_retry,
    _llm_call_with_retry,
)


class _Boom:
    """A provider that always fails with the given message."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ARG002
        self.calls += 1
        raise RuntimeError(self.message)

    async def astream(self, messages):  # noqa: ARG002
        self.calls += 1
        raise RuntimeError(self.message)
        yield  # pragma: no cover — makes this an async generator


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


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 - rate limited",
        "429 Too Many Requests",
        "HTTP 429",
        "you have hit the rate limit",
        "ratelimit exceeded",
    ],
)
def test_rate_limit_messages_are_recognised(message):
    assert _is_429(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        # Unrelated words that contain "rate" used to be treated as 429s, which
        # cost a 0.5 s backoff, a pointless retry, and a false increment of the
        # minimax_429s tile.
        "content was flagged by the moderation service",
        "corporate policy blocked the request",
        "connection reset by peer",
        "bad gateway",
        "timeout after 60 seconds",
    ],
)
def test_unrelated_errors_are_not_rate_limits(message):
    assert _is_429(RuntimeError(message)) is False


def test_status_code_attribute_wins_over_message_text():
    class _Err(Exception):
        status_code = 429

    class _ErrOther(_Err):
        status_code = 500

    assert _is_429(_Err("anything at all")) is True
    assert _is_429(_ErrOther("rate limit mentioned in passing")) is False


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


def test_failover_chain_follows_the_operator_ranked_order(monkeypatch):
    """The settings-page order decides who is tried first when the default
    provider dies, not the hardcoded historic sequence."""
    from app.graph.factories import _build_failover_chain

    rec = _RecordingBuilders(monkeypatch)
    minimax, openrouter, custom = _configs(default_provider="minimax")

    _build_failover_chain(
        minimax_config=minimax,
        openrouter_config=openrouter,
        custom_config=custom,
        failover_order=("custom", "openrouter", "minimax"),
    )

    assert rec.built == ["custom:cu-agent", "openrouter:or-agent"]


def test_failover_chain_treats_a_partial_order_as_a_ranking(monkeypatch):
    """Providers the operator ranked move ahead; unranked ones trail in the
    canonical order instead of being dropped from the chain."""
    from app.graph.factories import _build_failover_chain

    rec = _RecordingBuilders(monkeypatch)
    minimax, openrouter, custom = _configs(default_provider="openrouter")

    _build_failover_chain(
        minimax_config=minimax,
        openrouter_config=openrouter,
        custom_config=custom,
        failover_order=("custom",),
    )

    assert rec.built == ["custom:cu-agent", "minimax:mm-agent"]


# ── Streaming path (progressive delivery) ────────────────────────────────────


class _Streaming:
    """A provider that yields text chunks, optionally failing mid-stream."""

    def __init__(self, chunks, *, fail_after: int | None = None, fail_with: str = "connection reset"):
        self.chunks = chunks
        self.fail_after = fail_after
        self.fail_with = fail_with
        self.calls = 0

    async def astream(self, messages):  # noqa: ARG002
        self.calls += 1
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError(self.fail_with)
            yield _chunk(chunk)


def _chunk(text):
    from langchain_core.messages import AIMessageChunk

    return AIMessageChunk(content=text)


async def test_streaming_forwards_every_delta_and_merges_the_message():
    provider = _Streaming(["Dạ ", "lương ", "10 triệu", " ạ."])
    seen: list[str] = []

    async def on_delta(text):
        seen.append(text)

    message, backoff_ms = await _llm_call_streaming_with_retry(
        provider, ["m"], on_delta=on_delta
    )

    assert seen == ["Dạ ", "lương ", "10 triệu", " ạ."]
    assert message.content == "Dạ lương 10 triệu ạ."
    assert backoff_ms == 0
    assert provider.calls == 1


async def test_streaming_merged_message_exposes_tool_calls_for_the_loop():
    """A tool round must still look like a normal response to the agent loop."""
    from langchain_core.messages import AIMessageChunk

    class _ToolStreaming:
        async def astream(self, messages):  # noqa: ARG002
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "search_knowledge",
                        "args": '{"query": "luong"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )

    seen: list[str] = []

    async def on_delta(text):
        seen.append(text)

    message, _ = await _llm_call_streaming_with_retry(
        _ToolStreaming(), ["m"], on_delta=on_delta
    )

    assert seen == []  # no visible text on a tool round → nothing is sent early
    assert [c["name"] for c in message.tool_calls] == ["search_knowledge"]


async def test_streaming_fails_over_cleanly_before_the_first_token():
    spent = _Boom("insufficient balance")
    spare = _Streaming(["từ ", "nhà cung cấp dự phòng"])
    metrics: dict = {}

    async def on_delta(text):  # noqa: ARG001
        return None

    message, backoff_ms = await _llm_call_streaming_with_retry(
        spent, ["m"], on_delta=on_delta, metrics=metrics, fallback_bounds=[spare]
    )

    assert message.content == "từ nhà cung cấp dự phòng"
    assert backoff_ms == 0
    assert metrics["llm_failover"] is True
    assert metrics["llm_failover_reason"] == "quota_exhausted"
    assert "stream_partial" not in metrics


async def test_mid_stream_capacity_failure_is_recorded_as_partial_delivery():
    """Text already sent cannot be recalled, so a mid-stream failover is marked."""
    primary = _Streaming(
        ["Dạ ", "em ", "kiểm tra nhé"], fail_after=2, fail_with="insufficient balance"
    )
    spare = _Streaming(["phần còn lại"])
    metrics: dict = {}

    async def on_delta(text):  # noqa: ARG001
        return None

    message, _ = await _llm_call_streaming_with_retry(
        primary, ["m"], on_delta=on_delta, metrics=metrics, fallback_bounds=[spare]
    )

    assert message.content == "phần còn lại"
    assert metrics["stream_partial"] is True
    assert metrics["llm_failover_reason"] == "quota_exhausted"


async def test_generic_mid_stream_failure_still_propagates():
    """Non-capacity errors keep the old contract: the turn degrades, no failover."""
    primary = _Streaming(["Dạ ", " em"], fail_after=1, fail_with="connection reset")
    spare = _Streaming(["should not be used"])
    metrics: dict = {}

    async def on_delta(text):  # noqa: ARG001
        return None

    with pytest.raises(RuntimeError):
        await _llm_call_streaming_with_retry(
            primary, ["m"], on_delta=on_delta, metrics=metrics, fallback_bounds=[spare]
        )
    assert metrics == {}


async def test_mid_stream_failover_does_not_re_emit_the_already_delivered_prefix():
    """The replacement re-runs the whole completion, so its prefix is dropped.

    This is the case a per-chunk ``startswith`` check gets wrong: the
    replacement's first chunk ("Dạ em") is only a PARTIAL repeat of what the
    dead provider already emitted ("Dạ em kiểm tra thông tin"), and the repeat
    straddles three of its chunks. Overlap is therefore measured against the
    concatenated emitted text, not against the previous chunk.
    """
    primary = _Streaming(
        ["Dạ em kiểm tra ", "thông tin", " tuyển dụng"],
        fail_after=2,
        fail_with="insufficient balance",
    )
    spare = _Streaming(
        ["Dạ em", " kiểm tra thông tin", " tuyển dụng cho anh/chị ngay ạ."]
    )
    seen: list[str] = []
    metrics: dict = {}

    async def on_delta(text):
        seen.append(text)

    message, _ = await _llm_call_streaming_with_retry(
        primary, ["m"], on_delta=on_delta, metrics=metrics, fallback_bounds=[spare]
    )

    # The candidate-visible transcript is the concatenation of the deltas: the
    # dead provider's prefix followed by ONLY what the replacement added.
    transcript = "".join(seen)
    assert transcript == "Dạ em kiểm tra thông tin tuyển dụng cho anh/chị ngay ạ."
    assert transcript == message.content
    assert transcript.count("Dạ em kiểm tra thông tin") == 1
    assert metrics["stream_overlap_suppressed"] == len("Dạ em kiểm tra thông tin")
    assert metrics["stream_partial"] is True


async def test_mid_stream_failover_forwards_a_genuinely_different_answer():
    """No overlap means no suppression: the replacement's answer is forwarded whole.

    The dead provider's text cannot be recalled, so the only remaining honest
    outcome is the replacement's own answer appended after it — dropping it
    would leave the candidate with a dead provider's fragment and no reply.
    """
    primary = _Streaming(
        ["Công ty nào đang tuyển", " ở Hà Nội?"],
        fail_after=1,
        fail_with="insufficient balance",
    )
    spare = _Streaming(["Hiện tôi chưa kiểm tra được thông tin tuyển dụng ạ."])
    seen: list[str] = []
    metrics: dict = {}

    async def on_delta(text):
        seen.append(text)

    message, _ = await _llm_call_streaming_with_retry(
        primary, ["m"], on_delta=on_delta, metrics=metrics, fallback_bounds=[spare]
    )

    # The candidate's transcript keeps the dead provider's text (it cannot be
    # recalled) and then the replacement's whole answer — nothing dropped.
    assert "".join(seen) == (
        "Công ty nào đang tuyển" + "Hiện tôi chưa kiểm tra được thông tin tuyển dụng ạ."
    )
    # The merged message is the REPLACEMENT's answer, which is what the agent
    # loop returns as the turn's reply.
    assert message.content == "Hiện tôi chưa kiểm tra được thông tin tuyển dụng ạ."
    assert "stream_overlap_suppressed" not in metrics


async def test_429_retry_after_partial_stream_does_not_re_emit_the_prefix():
    """A same-provider 429 retry re-runs the completion too, and is de-duped the same.

    The retry path had the identical duplication: the second ``astream`` replays
    the whole answer, so a mid-stream 429 re-sent the already-delivered prefix.
    """

    class _RetryAfterPrefix:
        """Streams a prefix, fails with a 429, then replays a completed answer."""

        def __init__(self) -> None:
            self.calls = 0

        async def astream(self, _messages):
            from langchain_core.messages import AIMessageChunk

            self.calls += 1
            if self.calls == 1:
                yield AIMessageChunk(content="Lương thỏa thuận ")
                yield AIMessageChunk(content="từ 10 triệu")
                raise RuntimeError("429 rate limit")
            # The retry replays the same completion and then continues it.
            yield AIMessageChunk(content="Lương thỏa thuận ")
            yield AIMessageChunk(content="từ 10 triệu trở lên ạ.")

    seen: list[str] = []
    metrics: dict = {}

    async def on_delta(text):
        seen.append(text)

    provider = _RetryAfterPrefix()
    message, backoff_ms = await _llm_call_streaming_with_retry(
        provider, ["m"], on_delta=on_delta, metrics=metrics
    )

    assert provider.calls == 2
    assert backoff_ms >= 0
    assert "".join(seen) == "Lương thỏa thuận từ 10 triệu trở lên ạ."
    assert "".join(seen) == message.content
