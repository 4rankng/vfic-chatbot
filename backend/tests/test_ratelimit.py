"""Characterization of the auth rate limiter in core.ratelimit.

Pins the three load-bearing behaviours: it is a no-op in development (so local
dev and the unit suite aren't throttled), it 429s once a bucket exceeds its
limit in production, and it fails open (never blocks auth) when Redis is
unavailable. No live Redis — the production branch is exercised against a
counting fake.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core import ratelimit


def _request(xff: str | None = None, host: str = "10.0.0.1") -> SimpleNamespace:
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, window: int) -> None:
        self.expiries[key] = window


def _boom(*_args, **_kwargs):
    raise RuntimeError("redis must not be touched in this code path")


@pytest.mark.asyncio
async def test_noop_in_development(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="development"))
    # get_redis must never be called in dev; if it were, _boom would fire.
    monkeypatch.setattr(ratelimit, "get_redis", _boom)
    await ratelimit.enforce_rate_limit(_request(), "login", limit=0, window=60)
    await ratelimit.enforce_rate_limit_key("login", "user@example.com", limit=0, window=60)


@pytest.mark.asyncio
async def test_allows_up_to_limit_then_429s_in_production(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)

    req = _request(xff="203.0.113.7")
    # limit=3 -> the first three calls are allowed (and seed the TTL once).
    for _ in range(3):
        await ratelimit.enforce_rate_limit(req, "login", limit=3, window=120)

    assert fake.store["rl:login:203.0.113.7"] == 3
    assert fake.expiries["rl:login:203.0.113.7"] == 120

    with pytest.raises(HTTPException) as exc:
        await ratelimit.enforce_rate_limit(req, "login", limit=3, window=120)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_enforce_rate_limit_key_normalizes_bucket(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)

    # Mixed-case / padded email collapses to the same bucket key.
    await ratelimit.enforce_rate_limit_key("reset", "  User@Example.com ", limit=5, window=60)
    assert "rl:reset:user@example.com" in fake.store


@pytest.mark.asyncio
async def test_fails_open_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    monkeypatch.setattr(ratelimit, "get_redis", _boom)
    # Auth availability trumps rate limiting: a Redis hiccup must not 429.
    await ratelimit.enforce_rate_limit(_request(), "login", limit=1, window=60)


def test_client_ip_honours_x_forwarded_for_first_hop():
    assert ratelimit._client_ip(_request(xff="203.0.113.7, 10.0.0.1")) == "203.0.113.7"
    assert ratelimit._client_ip(_request(xff="203.0.113.7")) == "203.0.113.7"


def test_client_ip_falls_back_to_direct_client():
    assert ratelimit._client_ip(_request(host="198.51.100.4")) == "198.51.100.4"


def test_client_ip_unknown_when_no_client():
    assert ratelimit._client_ip(SimpleNamespace(headers={}, client=None)) == "unknown"
