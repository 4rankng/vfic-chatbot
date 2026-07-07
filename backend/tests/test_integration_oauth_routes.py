"""Unit tests for the Zalo OAuth route helpers (no DB / no Redis / no network).

The full FastAPI handlers need a live DB + Redis, which this repo's unit suite
deliberately avoids. We cover the pure helpers they delegate to, plus the
postMessage HTML sanitization.
"""
import json
import uuid

import pytest

from app.api import integrations as routes


class _FakeSettings:
    zalo_oa_oauth_redirect_url = ""
    cors_origins = "https://crm.example.com"
    cors_origins_list = ["https://crm.example.com"]


class _FakeUrl:
    def __init__(self, scheme: str, netloc: str) -> None:
        self.scheme = scheme
        self.netloc = netloc


class _FakeRequest:
    def __init__(self, headers: dict, *, scheme="http", netloc="localhost:8000") -> None:
        self.headers = headers
        self.url = _FakeUrl(scheme, netloc)


def test_oauth_redirect_uri_prefers_explicit_setting():
    settings = _FakeSettings()
    settings.zalo_oa_oauth_redirect_url = "https://bot.example.com/cb/"
    assert (
        routes._oauth_redirect_uri(settings, _FakeRequest({}))
        == "https://bot.example.com/cb"
    )


def test_oauth_redirect_uri_derives_from_forwarded_headers():
    request = _FakeRequest(
        {"x-forwarded-proto": "https", "x-forwarded-host": "bot.tingting.vip"}
    )
    uri = routes._oauth_redirect_uri(_FakeSettings(), request)
    assert uri == "https://bot.tingting.vip/api/v1/admin/integrations/zalo/oauth/callback"


def test_oauth_redirect_uri_falls_back_to_request_url():
    request = _FakeRequest({}, scheme="https", netloc="direct.example.com")
    uri = routes._oauth_redirect_uri(_FakeSettings(), request)
    assert uri.endswith("/api/v1/admin/integrations/zalo/oauth/callback")
    assert uri.startswith("https://direct.example.com/")


def test_callback_html_embeds_payload_and_neutralizes_script_breakout():
    payload = {
        "type": "zalo_oauth_error",
        # A crafted upstream error string must not escape the <script> tag.
        "message": "boom </script><script>alert(1)</script>",
    }
    response = routes._callback_html("https://crm.example.com", payload=payload)

    body = response.body.decode("utf-8")
    # The literal payload type is present...
    assert "zalo_oauth_error" in body
    # ...but no unescaped </script> survives to break the tag.
    assert "</script><script>" not in body
    # targetOrigin is restricted to the CRM origin (never "*").
    assert "https://crm.example.com" in body


@pytest.mark.asyncio
async def test_redis_set_state_stores_single_use_payload(monkeypatch):
    captured: dict = {}

    class _FakeRedis:
        async def set(self, key, value, ex=None, nx=None):
            captured["key"] = key
            captured["value"] = value
            captured["ex"] = ex

    monkeypatch.setattr(routes, "get_redis", lambda: _FakeRedis())

    admin_id = uuid.uuid4()
    await routes.redis_set_state(
        "STATE-1",
        admin_id,
        "https://bot.example.com/api/v1/admin/integrations/zalo/oauth/callback",
        "https://crm.example.com",
    )

    assert captured["key"] == routes._OAUTH_STATE_KEY.format(state="STATE-1")
    assert captured["ex"] == routes._OAUTH_STATE_TTL_SECONDS
    payload = json.loads(captured["value"])
    assert payload["admin_id"] == str(admin_id)
    assert payload["redirect_uri"].endswith("/oauth/callback")
    # The opener origin is pinned so the public callback never guesses it.
    assert payload["target_origin"] == "https://crm.example.com"


class _FakeResp:
    def __init__(self, payload) -> None:
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttpxClient:
    def __init__(self, *_, **__) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return _FakeResp(self._payload_for(url))

    _payload = {"data": {"oa_name": "Ting Ting OA"}}

    @classmethod
    def _payload_for(cls, _url):
        return cls._payload


@pytest.mark.asyncio
async def test_fetch_oa_display_name_parses_nested_oa_name(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeHttpxClient)
    name = await routes.fetch_oa_display_name("AT")
    assert name == "Ting Ting OA"


@pytest.mark.asyncio
async def test_fetch_oa_display_name_returns_empty_on_failure(monkeypatch):
    class _BoomClient(_FakeHttpxClient):
        async def get(self, url, headers=None):
            raise RuntimeError("network down")

    monkeypatch.setattr("httpx.AsyncClient", _BoomClient)
    assert await routes.fetch_oa_display_name("AT") == ""
