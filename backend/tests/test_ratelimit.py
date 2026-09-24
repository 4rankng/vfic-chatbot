"""Characterization of the rate limiter in core.ratelimit + its API adapters.

Pins the load-bearing behaviours: it is a no-op in development (so local dev and
the unit suite aren't throttled), it 429s once a bucket exceeds its limit in
production, it fails open (never blocks auth) when Redis is unavailable unless
the caller opts into fail-closed (the SEC-04 LLM bucket), and the API-facing
adapters in app.shared.infrastructure.rate_limits bucket per IP (webhooks) and
per user id (one bucket per route). No live Redis — the production branch is
exercised against a counting fake.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import ratelimit
from app.shared.infrastructure import rate_limits as api_rate_limits


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


@pytest.mark.asyncio
async def test_fails_closed_when_asked_and_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    monkeypatch.setattr(ratelimit, "get_redis", _boom)

    # A caller guarding a deployment-wide resource opts into denying rather than
    # admitting traffic whose budget it cannot verify.
    with pytest.raises(HTTPException) as exc:
        await ratelimit.enforce_rate_limit(
            _request(), "llm-user", limit=5, window=60, fail_open=False
        )
    assert exc.value.status_code == 429
    assert exc.value.detail != ratelimit._TOO_MANY_REQUESTS  # not an over-limit 429


@pytest.mark.asyncio
async def test_fail_closed_still_admits_requests_when_redis_is_healthy(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_settings", lambda: SimpleNamespace(app_env="production"))
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)

    await ratelimit.enforce_rate_limit_key("llm", "u1", limit=1, window=60, fail_open=False)

    with pytest.raises(HTTPException) as exc:
        await ratelimit.enforce_rate_limit_key("llm", "u1", limit=1, window=60, fail_open=False)
    assert exc.value.status_code == 429
    assert exc.value.detail == ratelimit._TOO_MANY_REQUESTS


# --- SEC-04 API adapters -----------------------------------------------------


def _production_settings(**overrides) -> SimpleNamespace:
    values = {
        "app_env": "production",
        "ratelimit_webhook_limit": 3,
        "ratelimit_webhook_window_seconds": 60,
        "ratelimit_llm_limit": 3,
        "ratelimit_llm_window_seconds": 60,
        "ratelimit_llm_fail_closed": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _install(monkeypatch, fake, **overrides) -> None:
    settings = _production_settings(**overrides)
    # Both modules read settings: the adapters for limits/windows, core for the
    # development no-op.
    monkeypatch.setattr(api_rate_limits, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)


@pytest.mark.asyncio
async def test_webhook_limiter_buckets_by_client_ip(monkeypatch):
    fake = _FakeRedis()
    _install(monkeypatch, fake)

    request = _request(xff="203.0.113.9")
    for _ in range(3):
        await api_rate_limits.enforce_webhook_rate_limit(request)

    assert fake.store["rl:webhook:203.0.113.9"] == 3
    assert fake.expiries["rl:webhook:203.0.113.9"] == 60

    with pytest.raises(HTTPException) as exc:
        await api_rate_limits.enforce_webhook_rate_limit(request)
    assert exc.value.status_code == 429

    # A different IP has its own bucket.
    await api_rate_limits.enforce_webhook_rate_limit(_request(xff="198.51.100.2"))
    assert fake.store["rl:webhook:198.51.100.2"] == 1


@pytest.mark.parametrize(
    ("limiter_name", "prefix"),
    [
        ("enforce_jobs_search_rate_limit", "jobs-search"),
        ("enforce_rag_test_rate_limit", "knowledge-rag-test"),
        ("enforce_web_chat_turn_rate_limit", "web-chat-turn"),
        ("enforce_lead_assist_rate_limit", "lead-assist"),
        ("enforce_lead_chatops_action_rate_limit", "lead-chatops-action"),
    ],
)
@pytest.mark.asyncio
async def test_each_user_route_limiter_has_its_own_bucket(monkeypatch, limiter_name, prefix):
    fake = _FakeRedis()
    _install(monkeypatch, fake)
    limiter = getattr(api_rate_limits, limiter_name)
    user_id = uuid4()

    for _ in range(3):
        await limiter(user_id)

    assert fake.store[f"rl:{prefix}:{user_id}"] == 3
    with pytest.raises(HTTPException) as exc:
        await limiter(user_id)
    assert exc.value.status_code == 429

    # Another user has its own bucket (the rejected call still counted against
    # the first user's window — that is the limiter, not a bug).
    other_user = uuid4()
    await limiter(other_user)
    assert fake.store[f"rl:{prefix}:{other_user}"] == 1
    assert fake.store[f"rl:{prefix}:{user_id}"] == 4


@pytest.mark.asyncio
async def test_two_user_routes_do_not_share_a_bucket(monkeypatch):
    fake = _FakeRedis()
    _install(monkeypatch, fake)
    user_id = uuid4()

    for _ in range(3):
        await api_rate_limits.enforce_lead_assist_rate_limit(user_id)

    with pytest.raises(HTTPException):
        await api_rate_limits.enforce_lead_assist_rate_limit(user_id)
    # A burst on the cheap route must not consume the expensive route's budget.
    await api_rate_limits.enforce_web_chat_turn_rate_limit(user_id)
    assert fake.store[f"rl:web-chat-turn:{user_id}"] == 1


@pytest.mark.asyncio
async def test_user_route_limiter_fails_closed_when_configured(monkeypatch):
    _install(monkeypatch, _boom, ratelimit_llm_fail_closed=True)

    with pytest.raises(HTTPException) as exc:
        await api_rate_limits.enforce_web_chat_turn_rate_limit(uuid4())
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_user_route_limiter_is_fail_open_by_default(monkeypatch):
    _install(monkeypatch, _boom)

    # Default contract: a Redis hiccup must not take the CRM's LLM routes down.
    await api_rate_limits.enforce_web_chat_turn_rate_limit(uuid4())


@pytest.mark.asyncio
async def test_webhook_limiter_is_a_noop_in_development(monkeypatch):
    settings = _production_settings(app_env="development")
    monkeypatch.setattr(api_rate_limits, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_redis", _boom)

    # Dev + the integration suite post many webhook events from loopback.
    await api_rate_limits.enforce_webhook_rate_limit(_request(xff="127.0.0.1"))
