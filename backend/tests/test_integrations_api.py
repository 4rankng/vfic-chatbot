from __future__ import annotations

import types
import uuid

import pytest

from app.api import integrations
from app.core.config import ZALO_BOT_WEBHOOK_URL, Settings
from app.services.integrations import llm_diagnostics, zalo_diagnostics
from app.schemas.integrations import ZaloIntegrationSettingsUpdate
from app.services.integration_settings import ZaloRuntimeConfig
from app.services.zalo_bot_service import SendResult
from app.shared.domain.errors import NotFoundError, ValidationError


class _Service:
    settings = Settings(app_env="development", zalo_bot_request_timeout=5)
    config = ZaloRuntimeConfig()

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self, account_key=None) -> ZaloRuntimeConfig:
        return self.config

    async def refresh_oa_access_token(self, account_key=None) -> str | None:
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloOASender", _OAClient)
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
            # A non-expiry failure stays on the local probe path. Expiry/refresh
            # diagnostics are covered below and intentionally use an OAuth call.
            return SendResult(ok=False, error="invalid oa-token")

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloOASender", _OAClient)
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
    assert result.errors == ["zalo_oa: invalid [redacted]"]


async def test_zalo_oa_reports_connected_after_successful_probe(monkeypatch):
    class _OAClient:
        def __init__(self, *, settings, access_token: str, refresh) -> None:
            assert settings is _Service.settings
            assert access_token == "oa-token"
            assert callable(refresh)

        async def get_oa_info(self) -> SendResult:
            return SendResult(ok=True)

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloOASender", _OAClient)
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
        async def refresh_oa_access_token(self, account_key=None) -> str | None:
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _RefreshService)
    monkeypatch.setattr(zalo_diagnostics, "ZaloOASender", _OAClient)
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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

    monkeypatch.setattr(zalo_diagnostics, "IntegrationSettingsService", _Service)
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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
        "zalo_bot_token": {"configured": True, "preview": "20 ký tự"},
        "zalo_bot_webhook_secret": {"configured": True, "preview": "24 ký tự"},
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

    async def resolve_zalo(self, account_key=None) -> ZaloRuntimeConfig:
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
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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
    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)
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

    monkeypatch.setattr(zalo_diagnostics, "ZaloBotAdminClient", _BotClient)

    status = await zalo_diagnostics.sync_bot_webhook(
        _PutService(object()), ["zalo_bot_webhook_secret"]
    )

    assert status["synced"] is False
    assert status["url"] == ZALO_BOT_WEBHOOK_URL
    assert status["error"] == "setWebhook: rejected [redacted]"


# ---------------------------------------------------------------------------
# Custom OpenAI-compatible provider (quota failover): /custom-llm
# ---------------------------------------------------------------------------


class _CustomLlmService:
    settings = Settings(app_env="development")

    def __init__(self, db) -> None:  # noqa: ARG002
        pass

    async def resolve_custom_llm(self):
        from app.services.integration_settings import CustomLlmRuntimeConfig

        return CustomLlmRuntimeConfig(
            api_key="sk-stored-secret",
            base_url="https://api.xiaomi.example/v1",
            agent_model="mimo-7b",
            enabled=True,
        )

    last_tests: dict = {}

    async def record_provider_test_result(self, provider: str, payload: dict) -> None:
        _CustomLlmService.last_tests[provider] = payload

    async def get_provider_test_result(self, provider: str) -> dict | None:
        return _CustomLlmService.last_tests.get(provider)

    async def admin_custom_llm_view(self) -> dict:
        return {
            "custom_llm_api_key": {"configured": True, "preview": "20 ký tự"},
            "custom_llm_base_url": "https://api.xiaomi.example/v1",
            "custom_llm_agent_model": "mimo-7b",
            "custom_llm_fast_model": "",
            "custom_llm_label": "Dự phòng",
            "custom_llm_enable": True,
            "custom_llm_usable": True,
            "llm_default_provider": "minimax",
            "llm_failover_order": ["minimax", "openrouter", "custom"],
        }

    async def update_custom_llm(self, values: dict, *, actor_id) -> list[str]:  # noqa: ARG002
        self.saved = values
        return list(values.keys())


class _PutTrackingService(_CustomLlmService):
    saved_calls: list = []

    async def update_custom_llm(self, values: dict, *, actor_id) -> list[str]:  # noqa: ARG002
        _PutTrackingService.saved_calls.append(dict(values))
        return list(values.keys())


async def test_custom_llm_get_returns_status_only_admin_view(monkeypatch):
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _CustomLlmService)

    view = await integrations.get_custom_llm_integration_settings(
        _admin=object(), db=object()
    )

    assert view.custom_llm_api_key.configured is True
    assert view.custom_llm_api_key.preview == "20 ký tự"
    assert view.custom_llm_usable is True
    assert view.custom_llm_enable is True


async def test_custom_llm_put_writes_through_service(monkeypatch):
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _PutTrackingService)
    _PutTrackingService.saved_calls = []

    from app.schemas.integrations import CustomLlmIntegrationSettingsUpdate

    body = CustomLlmIntegrationSettingsUpdate(custom_llm_enable=False)
    await integrations.update_custom_llm_integration_settings(
        body, admin=types.SimpleNamespace(id=uuid.uuid4()), db=object()
    )

    assert _PutTrackingService.saved_calls == [{"custom_llm_enable": False}]


async def test_custom_llm_test_reports_missing_fields_without_probe(monkeypatch):
    class _EmptyService(_CustomLlmService):
        async def resolve_custom_llm(self):
            from app.services.integration_settings import CustomLlmRuntimeConfig

            return CustomLlmRuntimeConfig()  # nothing stored, nothing supplied

    monkeypatch.setattr(llm_diagnostics, "IntegrationSettingsService", _EmptyService)

    called = False

    async def _must_not_probe(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.services.llm_probe.probe_openai_compatible_chat", _must_not_probe
    )

    result = await integrations.test_custom_llm_integration_settings(
        body=None, _admin=object(), db=object()
    )

    assert result.ok is False
    assert result.configured is False
    assert result.missing == [
        "custom_llm_api_key",
        "custom_llm_base_url",
        "custom_llm_agent_model",
    ]
    assert called is False


async def test_custom_llm_test_probes_supplied_credentials_before_save(monkeypatch):
    monkeypatch.setattr(llm_diagnostics, "IntegrationSettingsService", _CustomLlmService)
    seen: dict = {}

    async def _probe(**kwargs):
        seen.update(kwargs)
        from app.services.llm_probe import LlmProbeResult

        return LlmProbeResult(ok=True, latency_ms=123, sample="xin chào")

    monkeypatch.setattr("app.services.llm_probe.probe_openai_compatible_chat", _probe)

    from app.schemas.integrations import CustomLlmProbeIn

    body = CustomLlmProbeIn(
        custom_llm_api_key=" sk-brand-new-key ",
        custom_llm_base_url="https://staging.example/v1/",
    )

    result = await integrations.test_custom_llm_integration_settings(
        body=body, _admin=object(), db=object()
    )

    # Supplied values win so the operator can validate BEFORE saving; the
    # stored agent model fills the remaining gap. Trailing slash tolerated.
    assert seen == {
        "api_key": " sk-brand-new-key ",
        "base_url": "https://staging.example/v1/",
        "model": "mimo-7b",
    }
    assert result.ok is True
    assert result.latency_ms == 123
    assert result.sample == "xin chào"


async def test_custom_llm_test_error_is_never_raised_only_reported(monkeypatch):
    monkeypatch.setattr(llm_diagnostics, "IntegrationSettingsService", _CustomLlmService)

    async def _probe(**_kwargs):
        from app.services.llm_probe import LlmProbeResult

        return LlmProbeResult(ok=False, latency_ms=45, error="HTTP 401: bad sk-stored-secret")

    monkeypatch.setattr("app.services.llm_probe.probe_openai_compatible_chat", _probe)

    result = await integrations.test_custom_llm_integration_settings(
        body=None, _admin=object(), db=object()
    )

    assert result.ok is False
    # The probe used the STORED token (body was empty) — the error must say so,
    # otherwise the operator cannot tell which credential was rejected.
    assert result.error and result.error.startswith("HTTP 401: bad sk-stored-secret")
    assert "Access Token đã lưu" in result.error


# ---------------------------------------------------------------------------
# TingTing app API: GET/PUT /tingting
# ---------------------------------------------------------------------------


class _TingtingService:
    settings = Settings(app_env="development")
    stored: dict | None = None
    last_update: dict | None = None

    def __init__(self, _db) -> None:
        pass

    async def admin_tingting_view(self) -> dict:
        return _TingtingService.stored or {
            "api_key": {"configured": False, "preview": None},
            "configured": False,
            "base_url": "https://tingting.vip",
            "auth_header": "X-API-Key",
            "reset_oa_id": "",
        }

    async def update_tingting(self, values: dict, *, actor_id) -> dict:  # noqa: ANN001
        _TingtingService.last_update = {"values": values, "actor_id": actor_id}
        configured = bool(values.get("api_key"))
        _TingtingService.stored = {
            "api_key": {
                "configured": configured,
                "preview": f"{len(values['api_key'])} ký tự" if configured else None,
            },
            "configured": configured,
            "base_url": "https://tingting.vip",
            "auth_header": "X-API-Key",
            "reset_oa_id": values.get("reset_oa_id") or "",
        }
        return _TingtingService.stored


async def test_tingting_settings_get_reports_status_only(monkeypatch):
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _TingtingService)
    _TingtingService.stored = None

    result = await integrations.get_tingting_integration_settings(
        _admin=object(), db=object()
    )

    assert result.configured is False
    assert result.api_key.configured is False
    assert result.auth_header == "X-API-Key"


async def test_tingting_settings_put_stores_the_key_for_the_actor(monkeypatch):
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _TingtingService)
    admin = types.SimpleNamespace(id=uuid.uuid4())

    result = await integrations.update_tingting_integration_settings(
        body=integrations.TingtingIntegrationSettingsUpdate(api_key="ttk_live_key"),
        admin=admin,
        db=object(),
    )

    assert result.configured is True
    assert result.api_key.configured is True
    assert _TingtingService.last_update == {
        "values": {"api_key": "ttk_live_key"},
        "actor_id": admin.id,
    }


async def test_tingting_settings_put_pins_the_reset_oa(monkeypatch):
    """The admin names the OA that may run the reset flow."""
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _TingtingService)
    _TingtingService.stored = None
    admin = types.SimpleNamespace(id=uuid.uuid4())

    result = await integrations.update_tingting_integration_settings(
        body=integrations.TingtingIntegrationSettingsUpdate(reset_oa_id="tingting-oa-key"),
        admin=admin,
        db=object(),
    )

    assert result.reset_oa_id == "tingting-oa-key"
    assert _TingtingService.last_update["values"] == {"reset_oa_id": "tingting-oa-key"}


# ---------------------------------------------------------------------------
# Multi-OA: /zalo/oa-accounts
# ---------------------------------------------------------------------------


class _OaAccountRow:
    def __init__(self, account_key, label, status="ACTIVE", generation=1):
        self.account_key = account_key
        self.label = label
        self.status = status
        self.generation = generation


class _OaLifecycle:
    rows: list = []
    linked: dict | None = None
    unlinked: list[str] = []
    link_error: Exception | None = None
    unlink_error: Exception | None = None

    def __init__(self, _db) -> None:
        pass

    async def list_accounts(self):
        return list(self.rows)

    async def link(self, *, oa_id, label, credentials, actor_id=None):
        if type(self).link_error is not None:
            raise type(self).link_error
        type(self).linked = {
            "oa_id": oa_id,
            "label": label,
            "credentials": dict(credentials),
            "actor_id": actor_id,
        }
        return _OaAccountRow(oa_id, label)

    async def unlink(self, account_key, *, actor_id=None):
        if type(self).unlink_error is not None:
            raise type(self).unlink_error
        type(self).unlinked.append(account_key)


class _OaCredentialsView:
    settings = Settings(app_env="development", zalo_bot_request_timeout=5)

    def __init__(self, _db) -> None:
        pass

    async def oa_account_credentials_view(self, account_key):
        return {
            "account_key": account_key,
            "app_id": "" if account_key == "default:zalo_oa" else "app-1",
            "app_id_configured": account_key != "default:zalo_oa",
            "secret_key": {"configured": True, "preview": "…abcd"},
            "access_token": {"configured": True, "preview": "…1234"},
            "refresh_token": {"configured": False, "preview": None},
        }


def _patch_oa_accounts(monkeypatch, lifecycle=_OaLifecycle):
    import app.channels.providers.zalo_account as zalo_account_mod

    monkeypatch.setattr(integrations, "IntegrationSettingsService", _OaCredentialsView)
    monkeypatch.setattr(zalo_account_mod, "ZaloOaAccountLifecycle", lifecycle)


async def test_list_zalo_oa_accounts_flags_the_default(monkeypatch):
    _OaLifecycle.rows = [
        _OaAccountRow("default:zalo_oa", "OA gốc"),
        _OaAccountRow("123456", "Ting Ting Software Solution"),
    ]
    _patch_oa_accounts(monkeypatch)

    result = await integrations.list_zalo_oa_accounts(_admin=object(), db=object())

    assert [a.account_key for a in result.accounts] == ["default:zalo_oa", "123456"]
    assert result.accounts[0].is_default is True
    assert result.accounts[1].is_default is False
    assert result.accounts[1].app_id == "app-1"
    assert result.accounts[1].access_token.preview == "…1234"


async def test_link_zalo_oa_account_sends_every_credential(monkeypatch):
    _OaLifecycle.rows = []
    _OaLifecycle.linked = None
    _patch_oa_accounts(monkeypatch)
    admin = types.SimpleNamespace(id=uuid.uuid4())

    await integrations.link_zalo_oa_account(
        body=integrations.ZaloOaAccountLinkIn(
            oa_id="123456",
            label="Ting Ting Software Solution",
            app_id="app-1",
            secret_key="secret-1",
            access_token="access-1",
            refresh_token="refresh-1",
        ),
        admin=admin,
        db=object(),
    )

    assert _OaLifecycle.linked == {
        "oa_id": "123456",
        "label": "Ting Ting Software Solution",
        "credentials": {
            "zalo_oa_app_id": "app-1",
            "zalo_oa_secret_key": "secret-1",
            "zalo_oa_access_token": "access-1",
            "zalo_oa_refresh_token": "refresh-1",
        },
        "actor_id": admin.id,
    }


async def test_link_zalo_oa_account_maps_an_invalid_id_to_422(monkeypatch):
    from app.channels.providers.zalo_account import ZaloOaAccountInvalidError

    _OaLifecycle.rows = []
    _OaLifecycle.link_error = ZaloOaAccountInvalidError("mã OA phải là dãy số")
    _patch_oa_accounts(monkeypatch)
    try:
        with pytest.raises(ValidationError):
            await integrations.link_zalo_oa_account(
                body=integrations.ZaloOaAccountLinkIn(oa_id="abc", access_token="access-1"),
                admin=types.SimpleNamespace(id=uuid.uuid4()),
                db=object(),
            )
    finally:
        _OaLifecycle.link_error = None


async def test_unlink_zalo_oa_account_maps_a_missing_oa_to_404(monkeypatch):
    from app.channels.providers.zalo_account import ZaloOaAccountNotFoundError

    _OaLifecycle.rows = []
    _OaLifecycle.unlinked = []
    _OaLifecycle.unlink_error = ZaloOaAccountNotFoundError("chưa liên kết OA này")
    _patch_oa_accounts(monkeypatch)
    try:
        with pytest.raises(NotFoundError):
            await integrations.unlink_zalo_oa_account(
                account_key="123456", admin=types.SimpleNamespace(id=uuid.uuid4()), db=object()
            )
    finally:
        _OaLifecycle.unlink_error = None

    _OaLifecycle.rows = [_OaAccountRow("123456", "Ting Ting")]
    await integrations.unlink_zalo_oa_account(
        account_key="123456", admin=types.SimpleNamespace(id=uuid.uuid4()), db=object()
    )
    assert _OaLifecycle.unlinked == ["123456"]
