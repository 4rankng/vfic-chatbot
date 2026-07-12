from __future__ import annotations

import types
import uuid

from app.api import integrations
from app.core.config import ZALO_BOT_WEBHOOK_URL, Settings
from app.schemas.integrations import ZaloIntegrationSettingsUpdate
from app.services.integration_settings import ZaloRuntimeConfig
from app.services.zalo_bot_service import SendResult


class _Service:
    settings = Settings(app_env="development", zalo_bot_request_timeout=5)
    config = ZaloRuntimeConfig()

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self) -> ZaloRuntimeConfig:
        return self.config

    async def refresh_oa_access_token(self) -> str | None:
        return None


# ---------------------------------------------------------------------------
# Bot Platform channel: POST /zalo/bot/test
# ---------------------------------------------------------------------------


async def test_zalo_bot_reports_missing_token_without_live_probe(monkeypatch):
    called = False

    class _BotClient:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig()

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.configured is False
    assert result.connected is False
    assert result.missing == ["zalo_bot_token"]
    assert result.errors == []
    assert called is False


async def test_zalo_bot_redacts_token_in_error(monkeypatch):
    class _BotClient:
        def __init__(self, *, settings) -> None:
            assert settings.zalo_bot_token == "bot-secret"

        async def get_me(self) -> SendResult:
            return SendResult(ok=False, error="invalid bot-secret")

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig(bot_token="bot-secret")

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.configured is True
    assert result.connected is False
    assert result.missing == []
    assert result.errors == ["zalo_bot: invalid [redacted]"]


async def test_zalo_bot_reports_connected_after_successful_probe(monkeypatch):
    class _BotClient:
        def __init__(self, *, settings) -> None:
            assert settings.zalo_bot_token == "bot-secret"

        async def get_me(self) -> SendResult:
            return SendResult(ok=True)

        async def get_webhook_info(self) -> SendResult:
            return SendResult(ok=True, raw={"result": {"url": "https://x/webhooks/zalo/chatbot"}})

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig(bot_token="bot-secret")

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.connected is True
    assert result.errors == []
    assert result.webhook_registered is True
    assert result.webhook_url == "https://x/webhooks/zalo/chatbot"


# ---------------------------------------------------------------------------
# OA channel: POST /zalo/oa/test
# ---------------------------------------------------------------------------


async def test_zalo_oa_reports_missing_fields_without_live_probe(monkeypatch):
    called = False

    class _OAClient:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloOASender", _OAClient)
    _Service.config = ZaloRuntimeConfig()

    result = await integrations.test_zalo_oa(_admin=object(), db=object())

    assert result.configured is False
    assert result.connected is False
    assert result.missing == [
        "zalo_oa_app_id",
        "zalo_oa_secret_key",
        "zalo_oa_access_token",
        "zalo_oa_refresh_token",
    ]
    assert result.errors == []
    assert called is False


async def test_zalo_oa_redacts_token_in_error(monkeypatch):
    class _OAClient:
        def __init__(self, *, settings, access_token: str, refresh) -> None:
            assert settings is _Service.settings
            assert access_token == "oa-token"
            assert callable(refresh)

        async def get_oa_info(self) -> SendResult:
            return SendResult(ok=False, error="expired oa-token")

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloOASender", _OAClient)
    _Service.config = ZaloRuntimeConfig(
        oa_app_id="oa-app",
        oa_secret_key="oa-secret",
        oa_access_token="oa-token",
        oa_refresh_token="oa-refresh",
    )

    result = await integrations.test_zalo_oa(_admin=object(), db=object())

    assert result.configured is True
    assert result.connected is False
    assert result.missing == []
    assert result.errors == ["zalo_oa: expired [redacted]"]


async def test_zalo_oa_reports_connected_after_successful_probe(monkeypatch):
    class _OAClient:
        def __init__(self, *, settings, access_token: str, refresh) -> None:
            assert settings is _Service.settings
            assert access_token == "oa-token"
            assert callable(refresh)

        async def get_oa_info(self) -> SendResult:
            return SendResult(ok=True)

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloOASender", _OAClient)
    _Service.config = ZaloRuntimeConfig(
        oa_app_id="oa-app",
        oa_secret_key="oa-secret",
        oa_access_token="oa-token",
        oa_refresh_token="oa-refresh",
    )

    result = await integrations.test_zalo_oa(_admin=object(), db=object())

    assert result.connected is True
    assert result.errors == []


async def test_zalo_oa_refreshes_invalid_access_token_and_retries(monkeypatch):
    calls: list[str] = []

    class _RefreshService(_Service):
        async def refresh_oa_access_token(self) -> str | None:
            calls.append("refresh")
            return "oa-token-new"

    class _OAClient:
        def __init__(self, *, settings, access_token: str, refresh) -> None:
            assert settings is _RefreshService.settings
            assert access_token == "oa-token-old"
            self._token = access_token
            self._refresh = refresh

        async def get_oa_info(self) -> SendResult:
            calls.append(f"get:{self._token}")
            self._token = await self._refresh() or self._token
            calls.append(f"get:{self._token}")
            return SendResult(ok=True)

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _RefreshService)
    monkeypatch.setattr(integrations, "ZaloOASender", _OAClient)
    _RefreshService.config = ZaloRuntimeConfig(
        oa_app_id="oa-app",
        oa_secret_key="oa-secret",
        oa_access_token="oa-token-old",
        oa_refresh_token="oa-refresh",
    )

    result = await integrations.test_zalo_oa(_admin=object(), db=object())

    assert result.connected is True
    assert result.errors == []
    assert calls == ["get:oa-token-old", "refresh", "get:oa-token-new"]


# ---------------------------------------------------------------------------
# Bot webhook registration reporting: POST /zalo/bot/test getWebhookInfo
# ---------------------------------------------------------------------------


async def test_zalo_bot_reports_webhook_not_registered(monkeypatch):
    class _BotClient:
        def __init__(self, *, settings) -> None:
            pass

        async def get_me(self) -> SendResult:
            return SendResult(ok=True)

        async def get_webhook_info(self) -> SendResult:
            return SendResult(ok=True, raw={"result": {"url": ""}})

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig(bot_token="bot-secret")

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.connected is True
    assert result.webhook_registered is False
    assert result.webhook_url is None
    assert result.errors == []


async def test_zalo_bot_surfaces_getWebhookInfo_error(monkeypatch):
    class _BotClient:
        def __init__(self, *, settings) -> None:
            pass

        async def get_me(self) -> SendResult:
            return SendResult(ok=True)

        async def get_webhook_info(self) -> SendResult:
            return SendResult(ok=False, error="bad bot-secret")

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig(bot_token="bot-secret")

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.connected is True
    assert result.webhook_registered is False
    assert result.errors == ["getWebhookInfo: bad [redacted]"]


# ---------------------------------------------------------------------------
# Save-triggered webhook sync: PUT /zalo + _sync_bot_webhook
# ---------------------------------------------------------------------------


def _admin_view_dict() -> dict:
    return {
        "zalo_bot_token": {"configured": True, "preview": "abcd...1234"},
        "zalo_bot_webhook_secret": {"configured": True, "preview": "wxyz...9876"},
        "zalo_oa_app_id": {"configured": False, "value": None},
        "zalo_oa_secret_key": {"configured": False, "preview": None},
        "zalo_oa_access_token": {"configured": False, "preview": None},
        "zalo_oa_refresh_token": {"configured": False, "preview": None},
        "zalo_bot_api_base": "https://bot-api.zaloplatforms.com",
        "zalo_oa_api_base": "https://openapi.zalo.me",
        "zalo_oa_webhook_signature": None,
    }


class _PutService:
    settings = Settings(
        app_env="development",
        zalo_bot_request_timeout=5,
    )
    config = ZaloRuntimeConfig(bot_token="bot-secret", bot_webhook_secret="supersecret")
    changed = ["zalo_bot_webhook_secret"]

    def __init__(self, _db) -> None:
        pass

    async def update_zalo(self, _values, *, actor_id) -> list[str]:
        return self.changed

    async def admin_view(self) -> dict:
        return _admin_view_dict()

    async def resolve_zalo(self) -> ZaloRuntimeConfig:
        return self.config


async def test_update_zalo_pushes_webhook_secret_to_zalo(monkeypatch):
    calls: list[tuple[str, str]] = []

    class _BotClient:
        def __init__(self, *, settings) -> None:
            pass

        async def set_webhook(self, url: str, secret_token: str) -> SendResult:
            calls.append((url, secret_token))
            return SendResult(ok=True)

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _PutService)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _PutService.changed = ["zalo_bot_webhook_secret"]

    body = ZaloIntegrationSettingsUpdate(zalo_bot_webhook_secret="supersecret")
    admin = types.SimpleNamespace(id=uuid.uuid4())

    result = await integrations.update_zalo_integration_settings(
        body=body, admin=admin, db=object()
    )

    assert calls == [(ZALO_BOT_WEBHOOK_URL, "supersecret")]
    assert result.zalo_bot_webhook_sync is not None
    assert result.zalo_bot_webhook_sync.synced is True
    assert result.zalo_bot_webhook_sync.url == ZALO_BOT_WEBHOOK_URL


async def test_update_zalo_does_not_sync_when_only_oa_changed(monkeypatch):
    constructed = False

    class _BotClient:
        def __init__(self, *_a, **_kw) -> None:
            nonlocal constructed
            constructed = True

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _PutService)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _PutService.changed = ["zalo_oa_access_token"]

    body = ZaloIntegrationSettingsUpdate(zalo_oa_access_token="oa-token")
    admin = types.SimpleNamespace(id=uuid.uuid4())

    result = await integrations.update_zalo_integration_settings(
        body=body, admin=admin, db=object()
    )

    assert constructed is False
    assert result.zalo_bot_webhook_sync is not None
    assert result.zalo_bot_webhook_sync.synced is False
    assert result.zalo_bot_webhook_sync.skipped == "no bot token or webhook secret change"


async def test_sync_bot_webhook_surfaces_failure_without_raising(monkeypatch):
    class _BotClient:
        def __init__(self, *, settings) -> None:
            pass

        async def set_webhook(self, url: str, secret_token: str) -> SendResult:
            return SendResult(ok=False, error="rejected bot-secret")

    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)

    status = await integrations._sync_bot_webhook(
        _PutService(object()), ["zalo_bot_webhook_secret"]
    )

    assert status["synced"] is False
    assert status["url"] == ZALO_BOT_WEBHOOK_URL
    assert status["error"] == "setWebhook: rejected [redacted]"
