"""Unit tests for the Zalo OA OAuth client (no network)."""
import pytest

from app.services.zalo_oa_oauth import (
    ZaloOAOAuthClient,
    ZaloOAOAuthError,
)


class _FakeResp:
    def __init__(self, payload, *, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is _NOT_JSON:
            raise ValueError("not json")
        return self._payload


_NOT_JSON = object()


def _install_fake_httpx(monkeypatch, respond):
    """Replace httpx.AsyncClient with a fake that routes post() through `respond`.

    `respond(url, data, headers)` must return a `_FakeResp`. Captured calls are
    exposed on the returned `calls` list.
    """
    calls: list[dict] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, headers=None):
            calls.append({"url": url, "data": dict(data or {}), "headers": dict(headers or {})})
            return respond(url, data, headers)

    monkeypatch.setattr("app.services.zalo_oa_oauth.httpx.AsyncClient", _Client)
    return calls


def test_build_authorize_url_carries_app_id_redirect_and_state():
    url = ZaloOAOAuthClient("APP123", "SECRET").build_authorize_url(
        "https://bot.example.com/api/v1/admin/integrations/zalo/oauth/callback",
        "STATE-abc",
    )
    assert url.startswith("https://oauth.zaloapp.com/v4/oa/permission?")
    assert "app_id=APP123" in url
    assert "state=STATE-abc" in url
    assert "redirect_uri=https%3A%2F%2Fbot.example.com" in url


@pytest.mark.asyncio
async def test_exchange_code_posts_authorization_grant_and_parses_tokens(monkeypatch):
    def respond(url, data, headers):
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "CODE-1"
        assert data["redirect_uri"].endswith("/oauth/callback")
        assert data["app_id"] == "APP123"
        return _FakeResp(
            {"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600}
        )

    calls = _install_fake_httpx(monkeypatch, respond)
    token_set = await ZaloOAOAuthClient("APP123", "SECRET").exchange_code(
        "CODE-1", "https://bot.example.com/api/v1/admin/integrations/zalo/oauth/callback"
    )

    assert token_set.access_token == "AT-1"
    assert token_set.refresh_token == "RT-1"
    assert token_set.expires_in == 3600
    # secret_key travels in the header, never in the form body.
    assert calls[0]["headers"]["secret_key"] == "SECRET"
    assert "secret_key" not in calls[0]["data"]


@pytest.mark.asyncio
async def test_refresh_posts_refresh_grant_and_returns_rotated_token(monkeypatch):
    def respond(url, data, headers):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "RT-old"
        return _FakeResp(
            {"access_token": "AT-new", "refresh_token": "RT-rotated", "expires_in": 3600}
        )

    _install_fake_httpx(monkeypatch, respond)
    token_set = await ZaloOAOAuthClient("APP123", "SECRET").refresh("RT-old")

    assert token_set.access_token == "AT-new"
    assert token_set.refresh_token == "RT-rotated"


@pytest.mark.asyncio
async def test_token_endpoint_error_raises(monkeypatch):
    def respond(url, data, headers):
        return _FakeResp({"error": "invalid_code", "error_description": "expired"})

    _install_fake_httpx(monkeypatch, respond)
    with pytest.raises(ZaloOAOAuthError):
        await ZaloOAOAuthClient("APP123", "SECRET").exchange_code("bad", "https://x/cb")


@pytest.mark.asyncio
async def test_non_json_token_response_raises(monkeypatch):
    def respond(url, data, headers):
        return _FakeResp(_NOT_JSON, status_code=502, text="<html>down</html>")

    _install_fake_httpx(monkeypatch, respond)
    with pytest.raises(ZaloOAOAuthError):
        await ZaloOAOAuthClient("APP123", "SECRET").refresh("RT")
