from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.services.zalo_oa_service import ZaloOASender

pytestmark = pytest.mark.asyncio


async def test_oa_sender_uses_openapi_message_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-m1"}}

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.send_message("user-1", "hello")

    assert result.ok is True
    assert result.msg_id == "oa-m1"
    assert captured["url"] == "https://openapi.zalo.me/v3.0/oa/message/cs"
    assert captured["headers"] == {"access_token": "oa-token"}
    assert captured["json"] == {
        "recipient": {"user_id": "user-1"},
        "message": {"text": "hello"},
    }


async def test_oa_sender_get_oa_info_uses_read_only_profile_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"oa_id": "oa-1"}}

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, url: str, *, headers=None, **kw):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.get_oa_info()

    assert result.ok is True
    assert captured["url"] == "https://openapi.zalo.me/v2.0/oa/getoa"
    assert captured["headers"] == {"access_token": "oa-token"}


async def test_oa_sender_send_media_uses_cs_media_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": 0, "data": {"message_id": "oa-media-1"}}

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
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
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
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
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, *, json=None, headers=None, **kw):
            calls.append({"headers": headers})
            data = (
                {"error": -216, "message": "Access token invalid"}
                if len(calls) == 1
                else {"error": 0, "data": {"message_id": "oa-refreshed"}}
            )
            return _FakeResp(data)

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)

    refresh_calls: list[int] = []

    async def refresh() -> str | None:
        refresh_calls.append(1)
        return "new-token"

    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="old-token",
        refresh=refresh,
    )

    result = await sender.send_message("user-1", "hello")

    assert result.ok is True
    assert result.msg_id == "oa-refreshed"
    assert len(refresh_calls) == 1
    assert len(calls) == 2
    assert calls[0]["headers"] == {"access_token": "old-token"}
    assert calls[1]["headers"] == {"access_token": "new-token"}


async def test_oa_sender_without_refresh_returns_error_on_token_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResp:
        def json(self) -> dict[str, Any]:
            return {"error": -216, "message": "Access token invalid"}

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, *a: Any, **kw):
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
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
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, *, json=None, headers=None, **kw):
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    import app.services.zalo_oa_service as svc

    monkeypatch.setattr(svc.httpx, "AsyncClient", _FakeClient)
    sender = ZaloOASender(
        settings=Settings(app_env="development", zalo_bot_request_timeout=5),
        access_token="oa-token",
    )

    result = await sender.send_anonymous_message(phone="84901234567", text="Xin chào")

    assert result.ok is True
    assert result.msg_id == "oa-anon-1"
    assert captured["json"]["recipient"] == {"phone": "84901234567"}
    assert captured["json"]["message"] == {"text": "Xin chào"}
