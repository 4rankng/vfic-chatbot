"""Tests for token usage + cost accounting (Phase 6).

The parsing + cost-estimation logic is pure-Python and fully testable. The Redis
accumulation is best-effort and covered by the disabled-path / error-swallow tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph import usage as usage_mod
from app.graph.usage import TokenUsage, parse_usage


# --- parse_usage (handles every provider's usage shape) ----------------------


def test_parse_usage_dict_style():
    """Raw OpenAI response: dict with prompt_tokens / completion_tokens."""
    u = parse_usage({"prompt_tokens": 150, "completion_tokens": 80})
    assert u.prompt_tokens == 150
    assert u.completion_tokens == 80
    assert u.cached_tokens == 0
    assert u.total_tokens == 230


def test_parse_usage_dict_with_cached_tokens():
    u = parse_usage({"prompt_tokens": 150, "completion_tokens": 80, "cached_tokens": 60})
    assert u.cached_tokens == 60


def test_parse_usage_dict_with_prompt_cache_hit_tokens():
    """MiniMax-specific key for cache hits."""
    u = parse_usage({"prompt_tokens": 150, "completion_tokens": 80, "prompt_cache_hit_tokens": 40})
    assert u.cached_tokens == 40


def test_parse_usage_attribute_style():
    """langchain Usage object: attribute access."""
    u = parse_usage(
        SimpleNamespace(prompt_tokens=100, completion_tokens=50, prompt_cache_hit_tokens=20)
    )
    assert u.prompt_tokens == 100
    assert u.completion_tokens == 50
    assert u.cached_tokens == 20


def test_parse_usage_langchain_normalized_input_token_details_dict():
    """langchain-openai normalizes cache hits into ``input_token_details``.

    The agent loop feeds ``ai.usage_metadata`` (already normalized) into
    ``parse_usage``; before this shape was handled a real provider cache hit was
    recorded as 0, so cache telemetry always read "no caching" (PERF-05
    follow-up).
    """
    u = parse_usage(
        {
            "input_tokens": 12000,
            "output_tokens": 400,
            "total_tokens": 12400,
            "input_token_details": {"cache_creation": 0, "cache_read": 9000},
        }
    )
    assert u.prompt_tokens == 12000
    assert u.completion_tokens == 400
    assert u.cached_tokens == 9000


def test_parse_usage_nested_prompt_tokens_details_attribute_style():
    """OpenAI/OpenRouter nested ``prompt_tokens_details.cached_tokens``."""
    u = parse_usage(
        SimpleNamespace(
            prompt_tokens=500,
            completion_tokens=40,
            prompt_tokens_details=SimpleNamespace(cached_tokens=300),
        )
    )
    assert u.cached_tokens == 300


def test_parse_usage_input_token_details_attribute_style():
    u = parse_usage(
        SimpleNamespace(
            input_tokens=800,
            output_tokens=25,
            input_token_details=SimpleNamespace(cache_read=512),
        )
    )
    assert u.prompt_tokens == 800
    assert u.cached_tokens == 512


def test_parse_usage_direct_key_wins_over_nested():
    """A flat provider key is authoritative when both shapes are present."""
    u = parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 42,
            "input_token_details": {"cache_read": 7},
        }
    )
    assert u.cached_tokens == 42


def test_parse_usage_none_returns_zeros():
    u = parse_usage(None)
    assert u.total_tokens == 0


def test_parse_usage_garbage_returns_zeros():
    """Unrecognized input never raises — returns zeros."""
    assert parse_usage("not a dict").total_tokens == 0
    assert parse_usage(42).total_tokens == 0
    assert parse_usage({"unrelated": 1}).total_tokens == 0


def test_token_usage_total_property():
    assert TokenUsage(100, 50, 0).total_tokens == 150


# --- _estimate_cost ----------------------------------------------------------


def test_estimate_cost_zero_when_rates_unset(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace())
    u = TokenUsage(1000, 500, 0)
    assert usage_mod._estimate_cost(u) == 0.0


def test_estimate_cost_bills_input_plus_output(monkeypatch):
    """1M input at $1 + 1M output at $5 = $6 total."""
    from app.core import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(llm_cost_per_mtok_input=1.0, llm_cost_per_mtok_output=5.0),
    )
    u = TokenUsage(1_000_000, 1_000_000, 0)
    assert usage_mod._estimate_cost(u) == pytest.approx(6.0)


def test_estimate_cost_cached_tokens_are_free(monkeypatch):
    """Cached input tokens are subtracted from the billable amount."""
    from app.core import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(llm_cost_per_mtok_input=1.0, llm_cost_per_mtok_output=5.0),
    )
    # 1000 prompt, 800 cached → only 200 billable input + 500 output.
    u = TokenUsage(1000, 500, 800)
    expected = (200 / 1_000_000) * 1.0 + (500 / 1_000_000) * 5.0
    assert usage_mod._estimate_cost(u) == pytest.approx(expected)


# --- record_token_usage (best-effort, non-fatal) ----------------------------


class _FakeAsyncPipeline:
    """Records the queued commands + whether execute() was awaited."""

    def __init__(self) -> None:
        self.ops: list[tuple] = []
        self.executed = False

    def incrby(self, key, amount):
        self.ops.append(("incrby", key, amount))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        self.executed = True
        return [None] * len(self.ops)


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self.pipe = _FakeAsyncPipeline()

    def pipeline(self):
        return self.pipe


async def test_record_token_usage_zero_tokens_skips_redis(monkeypatch):
    """No tokens → no Redis call (early return)."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: pytest.fail("must not touch redis"))
    result = await usage_mod.record_token_usage(None)
    assert result.total_tokens == 0


async def test_record_token_usage_swallows_redis_error(monkeypatch):
    """A Redis failure must never propagate (best-effort contract)."""
    from app.core import redis as redis_mod

    async def _boom():
        raise RuntimeError("down")

    monkeypatch.setattr(redis_mod, "get_redis", _boom)
    # Should not raise; returns the parsed usage.
    result = await usage_mod.record_token_usage({"prompt_tokens": 100, "completion_tokens": 50})
    assert result.prompt_tokens == 100


async def test_record_token_usage_uses_async_client_and_keeps_key_names(monkeypatch):
    """REL-02: the per-response counters must go through the async client.

    The sync client is the blocking one; using it here put a Redis round trip on
    the event loop of every turn. The key names + TTLs are the dashboard
    contract, so they must survive the switch.
    """
    from app.core import redis as redis_mod

    fake = _FakeAsyncRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
    monkeypatch.setattr(
        redis_mod, "get_redis_sync", lambda: pytest.fail("blocking sync redis on the event loop")
    )
    # Cost rates off so the queued commands are exactly the three token counters
    # (the cost counter is covered by the _estimate_cost tests).
    from app.core import config as config_mod

    monkeypatch.setattr(
        config_mod,
        "get_settings",
        lambda: SimpleNamespace(llm_cost_per_mtok_input=0, llm_cost_per_mtok_output=0),
    )

    usage = await usage_mod.record_token_usage(
        {"prompt_tokens": 120, "completion_tokens": 30, "cached_tokens": 20}
    )

    assert usage.total_tokens == 150
    assert fake.pipe.executed
    day = usage_mod._today_utc()
    increments = {op[1]: op[2] for op in fake.pipe.ops if op[0] == "incrby"}
    assert increments == {
        f"llm:tokens:input:{day}": 120,
        f"llm:tokens:output:{day}": 30,
        f"llm:tokens:cached:{day}": 20,
    }
    expiring = {op[1] for op in fake.pipe.ops if op[0] == "expire"}
    assert f"llm:tokens:input:{day}" in expiring
    assert all(op[2] == usage_mod._TOKEN_TTL_SECONDS for op in fake.pipe.ops if op[0] == "expire")


# --- collect_token_usage -----------------------------------------------------


def test_collect_token_usage_returns_zeros_on_error(monkeypatch):
    from app.core import redis as redis_mod

    def _boom():
        raise RuntimeError("down")

    monkeypatch.setattr(redis_mod, "get_redis_sync", _boom)
    result = usage_mod.collect_token_usage()
    assert result["tokens_total"] == 0
    assert result["estimated_cost_usd"] == 0.0
    assert "day" in result
