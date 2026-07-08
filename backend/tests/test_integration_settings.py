import uuid

import pytest

from app.services.integration_settings import (
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
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    openrouter_api_key = ""
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v4-flash"
    openrouter_safety_model = "deepseek/deepseek-v4-flash"
    openrouter_digest_model = "deepseek/deepseek-v4-flash"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    embedding_dim = 3072


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
