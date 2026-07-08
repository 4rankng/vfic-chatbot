from __future__ import annotations

from app.api import integrations
from app.core.config import Settings
from app.services.integration_settings import ZaloRuntimeConfig
from app.services.zalo_bot_service import SendResult


class _Service:
    settings = Settings(app_env="development", zalo_bot_request_timeout=5)
    config = ZaloRuntimeConfig()

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self) -> ZaloRuntimeConfig:
        return self.config


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

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(integrations, "ZaloBotAdminClient", _BotClient)
    _Service.config = ZaloRuntimeConfig(bot_token="bot-secret")

    result = await integrations.test_zalo_bot(_admin=object(), db=object())

    assert result.connected is True
    assert result.errors == []


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
        def __init__(self, *, settings, access_token: str) -> None:
            assert settings is _Service.settings
            assert access_token == "oa-token"

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
        def __init__(self, *, settings, access_token: str) -> None:
            assert settings is _Service.settings
            assert access_token == "oa-token"

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
