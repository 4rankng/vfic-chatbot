import uuid

import pytest

from app.services.integration_settings import (
    FB_APP_ID,
    FB_APP_SECRET,
    FB_LOGIN_CONFIG_ID,
    FB_WEBHOOK_VERIFY_TOKEN,
    IntegrationSettingsCipher,
    IntegrationSettingsService,
    MINIMAX_API_KEY,
    OPENROUTER_API_KEY,
    ZALO_OA_REFRESH_TOKEN,
)


class _Settings:
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
    zalo_oa_refresh_token = ""
    minimax_api_key = ""
    minimax_enable = True
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    openrouter_api_key = ""
    openrouter_enable = False
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v4-flash"
    openrouter_safety_model = "deepseek/deepseek-v4-flash"
    openrouter_digest_model = "deepseek/deepseek-v4-flash"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    embedding_dim = 3072
    llm_default_provider = "minimax"
    # Meta / Facebook app credentials (env defaults — DB overrides per field).
    meta_app_id = ""
    meta_app_secret = ""
    meta_login_config_id = ""
    meta_webhook_verify_token = ""
    meta_graph_api_version = "v25.0"
    meta_graph_api_base = "https://graph.facebook.com"


class _Row:
    def __init__(self, key: str, encrypted_value: str) -> None:
        self.key = key
        self.encrypted_value = encrypted_value


class _ScalarResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _ReadDb:
    def __init__(self, rows) -> None:
        self.rows = rows

    async def scalars(self, _query):
        return _ScalarResult(self.rows)


class _WriteDb:
    def __init__(self) -> None:
        self.rows = {}
        self.added = []
        self.committed = False

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        self.rows[row.key] = row
        self.added.append(row)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_zalo_admin_view_masks_stored_refresh_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("refresh-token-for-zalo-oa")
    service = IntegrationSettingsService(
        _ReadDb([_Row(ZALO_OA_REFRESH_TOKEN, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_view()

    assert view["zalo_oa_refresh_token"] == {
        "configured": True,
        "preview": "refr...o-oa",
    }


@pytest.mark.asyncio
async def test_admin_view_skips_undecryptable_rows_and_falls_back_to_env(caplog):
    """A row sealed under a different key (or corrupt) must not 500 the admin view.

    Regression for `cryptography.exceptions.InvalidTag` raised from
    `_stored_values`: the row is skipped, a warning is logged with the key name
    (never the value), and the resolver falls back to Settings env vars exactly
    as if the row did not exist.
    """

    class _OtherSettings(_Settings):
        integration_settings_encryption_key = "different-key-than-runtime"

    sealed_under_other_key = IntegrationSettingsCipher(_OtherSettings()).encrypt(
        "refresh-token-for-zalo-oa"
    )

    env_settings = _Settings()
    env_settings.zalo_oa_app_id = "env-oa-app-id"  # env fallback is populated
    service = IntegrationSettingsService(
        _ReadDb([_Row(ZALO_OA_REFRESH_TOKEN, sealed_under_other_key)]),
        settings=env_settings,
    )

    with caplog.at_level("WARNING", logger="app.services.integration_settings"):
        view = await service.admin_view()

    # No exception; the corrupt row shows unconfigured (env refresh_token is "")
    # while a sibling env-backed key resolves normally.
    assert view["zalo_oa_refresh_token"] == {"configured": False, "preview": None}
    assert view["zalo_oa_app_id"] == {"configured": True, "value": "env-oa-app-id"}
    # The key name appears in the warning; the plaintext/ciphertext must not.
    assert any(
        ZALO_OA_REFRESH_TOKEN in rec.message and "refresh-token-for-zalo-oa" not in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_update_zalo_encrypts_refresh_token_and_audits_key_name(monkeypatch):
    audits = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_zalo(
        {"zalo_oa_refresh_token": " refresh-token-for-zalo-oa "},
        actor_id=actor_id,
    )

    assert changed == ["zalo_oa_refresh_token"]
    assert db.committed
    stored = db.rows[ZALO_OA_REFRESH_TOKEN]
    assert stored.encrypted_value.startswith("v1:")
    assert "refresh-token-for-zalo-oa" not in stored.encrypted_value
    assert service.cipher.decrypt(stored.encrypted_value) == "refresh-token-for-zalo-oa"
    assert audits == [
        {
            "action": "update_zalo_integration_settings",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "zalo",
            "payload": {"changed_keys": ["zalo_oa_refresh_token"]},
        }
    ]


@pytest.mark.asyncio
async def test_minimax_admin_view_masks_stored_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("sk-minimax-secret-token")
    service = IntegrationSettingsService(
        _ReadDb([_Row(MINIMAX_API_KEY, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_minimax_view()

    assert view["minimax_api_key"] == {
        "configured": True,
        "preview": "sk-m...oken",
    }
    assert view["minimax_base_url"] == "https://api.minimax.io/v1"
    assert view["minimax_agent_model"] == "MiniMax-M2.7-highspeed"
    assert view["minimax_enable"] is True
    assert view["llm_default_provider"] == "minimax"


@pytest.mark.asyncio
async def test_update_minimax_encrypts_token_and_audits_key_names(monkeypatch):
    audits = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_minimax(
        {"minimax_api_key": " sk-minimax-secret-token "},
        actor_id=actor_id,
    )

    assert changed == ["minimax_api_key"]
    assert db.committed
    stored = db.rows[MINIMAX_API_KEY]
    assert stored.encrypted_value.startswith("v1:")
    assert "sk-minimax-secret-token" not in stored.encrypted_value
    assert service.cipher.decrypt(stored.encrypted_value) == "sk-minimax-secret-token"
    assert audits == [
        {
            "action": "update_minimax_integration_settings",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "minimax",
            "payload": {"changed_keys": ["minimax_api_key"]},
        }
    ]


@pytest.mark.asyncio
async def test_update_minimax_stores_enable_as_non_secret(monkeypatch):
    async def fake_record_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())

    changed = await service.update_minimax(
        {"minimax_enable": False},
        actor_id=uuid.uuid4(),
    )

    assert changed == ["minimax_enable"]
    assert db.rows["minimax_enable"].encrypted_value == "False"
    assert db.rows["minimax_enable"].is_secret is False


@pytest.mark.asyncio
async def test_openrouter_admin_view_masks_stored_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("sk-or-v1-openrouter-secret-token")
    service = IntegrationSettingsService(
        _ReadDb([_Row(OPENROUTER_API_KEY, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_openrouter_view()

    assert view["openrouter_api_key"] == {
        "configured": True,
        "preview": "sk-o...oken",
    }
    assert view["openrouter_base_url"] == "https://openrouter.ai/api/v1"
    assert view["openrouter_digest_model"] == "deepseek/deepseek-v4-flash"
    assert view["openrouter_embedding_model"] == "openai/text-embedding-3-large"
    assert view["openrouter_embedding_dim"] == 3072
    assert view["openrouter_enable"] is False
    assert view["llm_default_provider"] == "minimax"


@pytest.mark.asyncio
async def test_update_openrouter_encrypts_token_and_audits_key_names(monkeypatch):
    audits = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_openrouter(
        {"openrouter_api_key": " sk-or-v1-openrouter-secret-token "},
        actor_id=actor_id,
    )

    assert changed == ["openrouter_api_key"]
    assert db.committed
    stored = db.rows[OPENROUTER_API_KEY]
    assert stored.encrypted_value.startswith("v1:")
    assert "sk-or-v1-openrouter-secret-token" not in stored.encrypted_value
    assert service.cipher.decrypt(stored.encrypted_value) == "sk-or-v1-openrouter-secret-token"
    assert audits == [
        {
            "action": "update_openrouter_integration_settings",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "openrouter",
            "payload": {"changed_keys": ["openrouter_api_key"]},
        }
    ]


@pytest.mark.asyncio
async def test_openrouter_admin_view_uses_stored_routing_and_model():
    service = IntegrationSettingsService(
        _ReadDb(
            [
                _Row("openrouter_enable", "true"),
                _Row("llm_default_provider", "openrouter"),
                _Row("openrouter_agent_model", "deepseek/deepseek-v4-flash"),
            ]
        ),
        settings=_Settings(),
    )

    view = await service.admin_openrouter_view()

    assert view["openrouter_enable"] is True
    assert view["llm_default_provider"] == "openrouter"
    assert view["openrouter_agent_model"] == "deepseek/deepseek-v4-flash"


# ─── Facebook OAuth credentials (DB-first, env fallback) ────────────────────


@pytest.mark.asyncio
async def test_facebook_oauth_admin_view_marks_unconfigured_when_empty():
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())

    view = await service.admin_facebook_oauth_view()

    assert view["facebook_app_id"] == {"configured": False, "value": None}
    assert view["facebook_app_secret"] == {"configured": False, "preview": None}
    assert view["facebook_login_config_id"] == {
        "configured": False,
        "value": None,
    }
    assert view["facebook_webhook_verify_token"] == {
        "configured": False,
        "preview": None,
    }


@pytest.mark.asyncio
async def test_facebook_oauth_admin_view_masks_secrets_and_surfaces_plaintext():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted_secret = seed.cipher.encrypt("1234567890abcdef")
    encrypted_verify = seed.cipher.encrypt("my-verify-token-1234")
    service = IntegrationSettingsService(
        _ReadDb(
            [
                _Row(FB_APP_ID, "fb-app-123"),
                _Row(FB_APP_SECRET, encrypted_secret),
                _Row(FB_LOGIN_CONFIG_ID, "login-cfg-9"),
                _Row(FB_WEBHOOK_VERIFY_TOKEN, encrypted_verify),
            ]
        ),
        settings=_Settings(),
    )

    view = await service.admin_facebook_oauth_view()

    # Plaintext fields surface their actual value (they appear in the browser
    # OAuth URL anyway).
    assert view["facebook_app_id"] == {"configured": True, "value": "fb-app-123"}
    assert view["facebook_login_config_id"] == {
        "configured": True,
        "value": "login-cfg-9",
    }
    # Secrets are masked.
    assert view["facebook_app_secret"] == {
        "configured": True,
        "preview": "1234...cdef",
    }
    assert view["facebook_webhook_verify_token"] == {
        "configured": True,
        "preview": "my-v...1234",
    }


@pytest.mark.asyncio
async def test_facebook_oauth_resolves_db_first_with_env_fallback():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted_secret = seed.cipher.encrypt("db-app-secret-value")
    service = IntegrationSettingsService(
        _ReadDb([_Row(FB_APP_SECRET, encrypted_secret)]),
        settings=_Settings(),
    )

    cfg = await service.resolve_facebook_oauth()

    # DB wins over the (empty) env default.
    assert cfg.app_secret == "db-app-secret-value"
    # Fields absent from DB fall back to the env default (empty here).
    assert cfg.app_id == ""
    assert cfg.graph_api_version == "v25.0"


@pytest.mark.asyncio
async def test_update_facebook_oauth_encrypts_secrets_keeps_plaintext_ids(monkeypatch):
    async def fake_record_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_facebook_oauth(
        {
            FB_APP_ID: "fb-app-123",
            FB_APP_SECRET: "1234567890abcdef",
            FB_LOGIN_CONFIG_ID: "login-cfg-9",
            FB_WEBHOOK_VERIFY_TOKEN: "verify-token-1234",
        },
        actor_id=actor_id,
    )

    assert changed == [
        FB_APP_ID,
        FB_APP_SECRET,
        FB_LOGIN_CONFIG_ID,
        FB_WEBHOOK_VERIFY_TOKEN,
    ]
    assert db.committed

    # Secrets are encrypted at rest.
    assert db.rows[FB_APP_SECRET].encrypted_value.startswith("v1:")
    assert db.rows[FB_WEBHOOK_VERIFY_TOKEN].encrypted_value.startswith("v1:")
    assert "1234567890abcdef" not in db.rows[FB_APP_SECRET].encrypted_value
    assert db.rows[FB_APP_SECRET].is_secret is True
    assert db.rows[FB_WEBHOOK_VERIFY_TOKEN].is_secret is True

    # Non-secret identifiers are stored as plaintext and flagged is_secret=False.
    assert db.rows[FB_APP_ID].encrypted_value == "fb-app-123"
    assert db.rows[FB_APP_ID].is_secret is False
    assert db.rows[FB_LOGIN_CONFIG_ID].encrypted_value == "login-cfg-9"
    assert db.rows[FB_LOGIN_CONFIG_ID].is_secret is False


@pytest.mark.asyncio
async def test_update_facebook_oauth_skips_blank_fields_leaving_them_unchanged(
    monkeypatch,
):
    """A PUT with only some fields populated must leave the others untouched
    ("leave blank to keep current value" semantics)."""
    async def fake_record_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())

    changed = await service.update_facebook_oauth(
        {FB_APP_ID: "   ", FB_APP_SECRET: None, FB_LOGIN_CONFIG_ID: "  cfg-9  "},
        actor_id=uuid.uuid4(),
    )

    # Only the populated, non-whitespace field is written.
    assert changed == [FB_LOGIN_CONFIG_ID]
    assert FB_APP_ID not in db.rows
    assert FB_APP_SECRET not in db.rows
    assert db.rows[FB_LOGIN_CONFIG_ID].encrypted_value == "cfg-9"
