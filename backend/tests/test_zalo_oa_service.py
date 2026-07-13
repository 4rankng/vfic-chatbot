from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.services.zalo_oa_service import ZaloOASender

from tests.helpers.http_fake import register_fake_client

pytestmark = pytest.mark.asyncio


async def test_oa_sender_uses_openapi_message_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-m1"}}

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.send_message("user-1", "hello", quote_message_id="inbound-1")

    assert result.ok is True
    assert result.msg_id == "oa-m1"
    assert captured["url"] == "https://openapi.zalo.me/v3.0/oa/message/cs"
    assert captured["headers"] == {"access_token": "oa-token"}
    assert captured["json"] == {
        "recipient": {"user_id": "user-1"},
        "message": {"text": "hello", "quote_message_id": "inbound-1"},
    }


async def test_oa_sender_get_oa_info_uses_read_only_profile_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"oa_id": "oa-1"}}

    class _FakeClient:
        async def get(self, url: str, *, headers=None, **kw):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.get_oa_info()

    assert result.ok is True
    assert captured["url"] == "https://openapi.zalo.me/v2.0/oa/getoa"
    assert captured["headers"] == {"access_token": "oa-token"}


async def test_oa_sender_get_oa_info_refreshes_invalid_token_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeResp:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

    class _FakeClient:
        async def get(self, url: str, *, headers=None, **kw):
            calls.append({"url": url, "headers": headers})
            if len(calls) == 1:
                return _FakeResp({"error": -216, "message": "Access token is invalid"})
            return _FakeResp({"error": 0, "data": {"oa_id": "oa-1"}})

    register_fake_client("zalo_oa", _FakeClient())
    refresh_calls: list[int] = []

    async def refresh() -> str | None:
        refresh_calls.append(1)
        return "oa-token-new"

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token-old",
        refresh=refresh,
    )

    result = await sender.get_oa_info()

    assert result.ok is True
    assert refresh_calls == [1]
    assert calls == [
        {
            "url": "https://openapi.zalo.me/v2.0/oa/getoa",
            "headers": {"access_token": "oa-token-old"},
        },
        {
            "url": "https://openapi.zalo.me/v2.0/oa/getoa",
            "headers": {"access_token": "oa-token-new"},
        },
    ]


async def test_oa_sender_get_oa_info_returns_original_error_when_refresh_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_calls: list[int] = []

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": -216, "message": "Access token is invalid"}

    class _FakeClient:
        async def get(self, url: str, *, headers=None, **kw):
            get_calls.append(1)
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())

    async def refresh() -> str | None:
        raise RuntimeError("redis unavailable")

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token-old",
        refresh=refresh,
    )

    result = await sender.get_oa_info()

    assert result.ok is False
    assert result.error == "Access token is invalid"
    assert get_calls == [1]


async def test_oa_sender_send_media_uses_cs_media_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-media-1"}}

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.send_media(
        "user-1",
        text="Ảnh JD",
        media_url="https://example.com/jd.png",
        media_type="image",
    )

    assert result.ok is True
    assert result.msg_id == "oa-media-1"
    assert captured["url"] == "https://openapi.zalo.me/v3.0/oa/message/cs"
    assert captured["headers"] == {"access_token": "oa-token"}
    assert captured["json"] == {
        "recipient": {"user_id": "user-1"},
        "message": {
            "text": "Ảnh JD",
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "media",
                    "elements": [
                        {
                            "media_type": "image",
                            "url": "https://example.com/jd.png",
                        }
                    ],
                },
            },
        },
    }


async def test_oa_sender_send_buttons_builds_button_template_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-btn-1"}}

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )
    buttons = [{"title": "Chat", "type": "oa.query.chat", "payload": "p1"}]

    result = await sender.send_buttons("user-1", text="Chọn:", buttons=buttons)

    assert result.ok is True
    assert result.msg_id == "oa-btn-1"
    assert captured["json"]["recipient"] == {"user_id": "user-1"}
    payload = captured["json"]["message"]["attachment"]["payload"]
    assert payload["template_type"] == "button"
    assert payload["buttons"] == buttons
    assert captured["json"]["message"]["text"] == "Chọn:"


async def test_oa_sender_send_retries_once_after_token_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeResp:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            calls.append({"headers": headers})
            data = (
                {"error": -216, "message": "Access token invalid"}
                if len(calls) == 1
                else {"error": 0, "data": {"message_id": "oa-refreshed"}}
            )
            return _FakeResp(data)

    register_fake_client("zalo_oa", _FakeClient())

    refresh_calls: list[int] = []

    async def refresh() -> str | None:
        refresh_calls.append(1)
        return "new-token"

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="old-token",
        refresh=refresh,
    )

    result = await sender.send_message("user-1", "hello", quote_message_id="inbound-1")

    assert result.ok is True
    assert result.msg_id == "oa-refreshed"
    assert len(refresh_calls) == 1
    assert len(calls) == 2
    assert calls[0]["headers"] == {"access_token": "old-token"}
    assert calls[1]["headers"] == {"access_token": "new-token"}


async def test_oa_sender_send_returns_original_error_when_refresh_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": -216, "message": "Access token is invalid"}

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            calls.append(1)
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())

    async def refresh() -> str | None:
        raise RuntimeError("redis unavailable")

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token-old",
        refresh=refresh,
    )

    result = await sender.send_message("user-1", "hello", quote_message_id="inbound-1")

    assert result.ok is False
    assert result.error == "chunk 1/1 failed: Access token is invalid"
    assert calls == [1]


async def test_oa_sender_without_refresh_returns_error_on_token_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": -216, "message": "Access token invalid"}

    class _FakeClient:
        async def post(self, *a: Any, **kw):
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="old-token",
    )

    result = await sender.send_message("user-1", "hello")

    assert result.ok is False
    assert result.error is not None


async def test_oa_sender_send_anonymous_uses_phone_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-anon-1"}}

    class _FakeClient:
        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.send_anonymous_message(phone="84901234567", text="Xin chào")

    assert result.ok is True
    assert result.msg_id == "oa-anon-1"
    assert captured["json"]["recipient"] == {"phone": "84901234567"}
    assert captured["json"]["message"] == {"text": "Xin chào"}


# ── get_user_detail (avatar/name profile lookup) ────────────────────


async def test_get_user_detail_encodes_data_param_and_parses_avatars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful lookup passes compact JSON to httpx (which URL-encodes once)."""
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {
                "error": 0,
                "data": {
                    "display_name": "Nguyễn Văn An",
                    "avatar": "https://zalo.me/a/full.jpg",
                    "avatars": {
                        "120": "https://zalo.me/a/120.jpg",
                        "240": "https://zalo.me/a/240.jpg",
                    },
                },
            }

    class _FakeClient:
        async def get(self, url: str, *, params=None, headers=None, **kw):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    profile = await sender.get_user_detail("user-abc")

    assert profile is not None
    # Priority: avatars.240 > avatar > avatars.120
    assert profile.avatar_url == "https://zalo.me/a/240.jpg"
    assert profile.display_name == "Nguyễn Văn An"
    assert captured["url"] == "https://openapi.zalo.me/v3.0/oa/user/detail"
    assert captured["headers"] == {"access_token": "oa-token"}
    # The data param is compact JSON passed raw — httpx URL-encodes it once
    # when building the query string. Pre-encoding here caused double-encoding
    # (Zalo saw %257B instead of %7B) and every lookup failed with -201.
    assert captured["params"]["data"] == '{"user_id":"user-abc"}'


async def test_get_user_detail_falls_back_to_avatar_when_no_240(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {
                "error": 0,
                "data": {
                    "display_name": "Lê Thị Bình",
                    "avatar": "https://zalo.me/b/full.jpg",
                },
            }

    class _FakeClient:
        async def get(self, url: str, *, params=None, headers=None, **kw):
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    profile = await sender.get_user_detail("user-b")

    assert profile is not None
    assert profile.avatar_url == "https://zalo.me/b/full.jpg"


async def test_get_user_detail_returns_none_on_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero error envelope (e.g. missing permission) yields None, not raise."""

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": -201, "message": "permission denied"}

    class _FakeClient:
        async def get(self, url: str, *, params=None, headers=None, **kw):
            return _FakeResp()

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    profile = await sender.get_user_detail("user-c")

    assert profile is None


async def test_get_user_detail_returns_none_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def get(self, url: str, *, params=None, headers=None, **kw):
            raise ConnectionError("network down")

    register_fake_client("zalo_oa", _FakeClient())
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    profile = await sender.get_user_detail("user-d")

    assert profile is None


async def test_get_user_detail_refreshes_token_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale-token envelope triggers one refresh + retry on user-detail."""
    calls: list[str] = []

    class _FakeResp:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def get(self, url: str, *, params=None, headers=None, **kw):
            calls.append(headers["access_token"])
            if len(calls) == 1:
                return _FakeResp({"error": -216, "message": "Access token is invalid"})
            return _FakeResp(
                {"error": 0, "data": {"display_name": "X", "avatar": "https://z/x.jpg"}}
            )

    register_fake_client("zalo_oa", _FakeClient())
    refresh_calls: list[int] = []

    async def refresh() -> str | None:
        refresh_calls.append(1)
        return "oa-token-new"

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token-old",
        refresh=refresh,
    )

    profile = await sender.get_user_detail("user-e")

    assert profile is not None
    assert profile.avatar_url == "https://z/x.jpg"
    assert refresh_calls == [1]
    assert calls == ["oa-token-old", "oa-token-new"]


async def test_get_user_detail_empty_user_id_returns_none() -> None:
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )
    assert await sender.get_user_detail("") is None
    assert await sender.get_user_detail("   ") is None


async def test_parse_oa_user_profile_priority() -> None:
    """Module-level parser picks 240 > avatar > 120."""
    from app.services.zalo_oa_service import _parse_oa_user_profile

    p1 = _parse_oa_user_profile({"avatar": "full", "avatars": {"240": "hi", "120": "lo"}})
    assert p1.avatar_url == "hi"

    p2 = _parse_oa_user_profile({"avatar": "full"})
    assert p2.avatar_url == "full"

    p3 = _parse_oa_user_profile({"avatars": {"120": "lo"}})
    assert p3.avatar_url == "lo"

    p4 = _parse_oa_user_profile({})
    assert p4.avatar_url == ""
    assert p4.display_name == ""
