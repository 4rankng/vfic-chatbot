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


def test_record_token_usage_zero_tokens_skips_redis(monkeypatch):
    """No tokens → no Redis call (early return)."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis_sync", lambda: pytest.fail("must not touch redis"))
    result = usage_mod.record_token_usage(None)
    assert result.total_tokens == 0


def test_record_token_usage_swallows_redis_error(monkeypatch):
    """A Redis failure must never propagate (best-effort contract)."""
    from app.core import redis as redis_mod

    def _boom():
        raise RuntimeError("down")

    monkeypatch.setattr(redis_mod, "get_redis_sync", _boom)
    # Should not raise; returns the parsed usage.
    result = usage_mod.record_token_usage({"prompt_tokens": 100, "completion_tokens": 50})
    assert result.prompt_tokens == 100


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
