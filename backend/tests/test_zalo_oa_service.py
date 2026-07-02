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
