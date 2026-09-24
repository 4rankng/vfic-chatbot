"""SEC-04 + SEC-05 on the inbound webhook surface.

The defects: all three webhook POSTs were unbounded (no rate limit) and each read
``request.body()`` in full before any size check, so an unauthenticated loop
could both drain the deployment and make the ASGI layer buffer an arbitrarily
large body.

These tests drive the real routes: the per-IP limiter rejects with 429 before any
other work, and the body ceiling rejects a declared-oversized Content-Length
before the body is read at all (plus a post-read check for a body that only
reveals its size while being read). No live Redis and no live DB — the limiter
runs against a counting fake and the routes are mounted on a bare FastAPI app.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import webhooks
from app.core import ratelimit
from app.services.ingestion.limits import MAX_WEBHOOK_BODY_BYTES
from app.shared.infrastructure import rate_limits as api_rate_limits
from app.shared.infrastructure.db import get_request_db

WEBHOOK_POST_PATHS = (
    "/webhooks/zalo/chatbot",
    "/webhooks/zalo/oa",
    "/webhooks/facebook",
)


class _CountingRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, window: int) -> None:
        return None


def _install_production_limiter(monkeypatch, *, limit: int, window: int = 60) -> _CountingRedis:
    """Run the limiter in production mode against a counting Redis fake."""
    settings = SimpleNamespace(
        app_env="production",
        ratelimit_webhook_limit=limit,
        ratelimit_webhook_window_seconds=window,
    )
    redis = _CountingRedis()
    monkeypatch.setattr(api_rate_limits, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_settings", lambda: settings)
    monkeypatch.setattr(ratelimit, "get_redis", lambda: redis)
    return redis


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(webhooks.router)
    # The limiter and the size guard both run before any DB use; a dummy session
    # keeps this test from opening one.
    app.dependency_overrides[get_request_db] = lambda: SimpleNamespace()
    return TestClient(app)


@pytest.mark.parametrize("path", WEBHOOK_POST_PATHS)
def test_every_webhook_post_is_rate_limited_before_any_other_work(monkeypatch, path) -> None:
    # limit=0 -> the very first POST is rejected, so the guard must run before
    # the body read, the DB lookup, and the provider-specific handling (none of
    # which this test provides).
    redis = _install_production_limiter(monkeypatch, limit=0)

    response = _client().post(path, content=b"{}")

    assert response.status_code == 429
    assert redis.counts, "the limiter must have counted the request"


def test_the_facebook_verify_route_is_rate_limited_too(monkeypatch) -> None:
    # Meta's subscribe/unsubscribe challenge is an unauthenticated DB read +
    # token compare; the per-IP budget (120/min) never affects a real handshake.
    redis = _install_production_limiter(monkeypatch, limit=0)

    response = _client().get("/webhooks/facebook?hub.mode=subscribe")

    assert response.status_code == 429
    assert redis.counts


def test_a_webhook_loop_is_rejected_once_the_limit_is_reached(monkeypatch) -> None:
    redis = _install_production_limiter(monkeypatch, limit=2)
    client = _client()

    # Malformed JSON reaches the 400 path without a DB; the third POST never gets
    # that far.
    codes = [
        client.post("/webhooks/zalo/chatbot", content=b"{not-json").status_code
        for _ in range(3)
    ]

    assert codes == [400, 400, 429]
    assert redis.counts["rl:webhook:testclient"] == 3


class _FakeRequest:
    """Minimal Request double for the webhook body guard.

    ``body`` is None when the test asserts the body must never be read.
    """

    def __init__(self, body: bytes | None = None, *, declared: int | None = None) -> None:
        self.headers = {} if declared is None else {"content-length": str(declared)}
        self._body = body

    async def body(self) -> bytes:
        assert self._body is not None, "an oversized body must not be read"
        return self._body


@pytest.mark.asyncio
async def test_declared_oversized_body_is_rejected_before_the_body_is_read() -> None:
    with pytest.raises(HTTPException) as exc:
        await webhooks.zalo_webhook(_FakeRequest(declared=MAX_WEBHOOK_BODY_BYTES + 1), db=None)

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_a_body_that_lies_about_its_size_is_rejected_after_reading() -> None:
    request = _FakeRequest(b"x" * (MAX_WEBHOOK_BODY_BYTES + 1))

    with pytest.raises(HTTPException) as exc:
        await webhooks.zalo_oa_webhook(request, db=None)

    assert exc.value.status_code == 413


def test_oversized_webhook_post_returns_413_over_http(monkeypatch) -> None:
    client = _client()

    response = client.post(
        "/webhooks/zalo/chatbot", content=b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
    )

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_a_body_exactly_at_the_ceiling_is_read_normally() -> None:
    # The ceiling is inclusive: the guard must reject only what is over it.
    at_ceiling = b"x" * MAX_WEBHOOK_BODY_BYTES

    assert await webhooks._read_body_within_limit(_FakeRequest(at_ceiling)) == at_ceiling
    assert (
        await webhooks._read_body_within_limit(
            _FakeRequest(at_ceiling, declared=MAX_WEBHOOK_BODY_BYTES)
        )
        == at_ceiling
    )
