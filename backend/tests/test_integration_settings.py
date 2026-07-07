import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.integration_settings import (
    IntegrationSettingsService,
    MINIMAX_API_KEY,
    OPENROUTER_API_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_ACCESS_TOKEN_EXPIRES_AT,
    ZALO_OA_APP_ID,
    ZALO_OA_REFRESH_TOKEN,
    ZALO_OA_SECRET_KEY,
)


class _Settings:
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
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


# ── OAuth (scan-to-connect) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zalo_admin_view_includes_oauth_connection_state():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())

    def enc(value: str) -> str:
        return seed.cipher.encrypt(value)

    rows = [
        _Row(ZALO_OA_ACCESS_TOKEN, enc("OA-ACCESS")),
        _Row(ZALO_OA_REFRESH_TOKEN, enc("OA-REFRESH")),
        _Row(ZALO_OA_ACCESS_TOKEN_EXPIRES_AT, enc("2099-01-01T00:00:00+00:00")),
    ]
    service = IntegrationSettingsService(_ReadDb(rows), settings=_Settings())

    view = await service.admin_view()

    # Refresh-token presence only — no preview of the long-lived credential.
    assert view["zalo_oa_refresh_token"] == {"configured": True}
    assert view["zalo_oa_connected"] is True
    assert view["zalo_oa_access_token_expires_at"].startswith("2099-")


@pytest.mark.asyncio
async def test_zalo_admin_view_reports_disconnected_without_refresh_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    rows = [_Row(ZALO_OA_ACCESS_TOKEN, seed.cipher.encrypt("OA-ACCESS"))]
    service = IntegrationSettingsService(_ReadDb(rows), settings=_Settings())

    view = await service.admin_view()

    # Manual token entry only -> not "connected" via OAuth.
    assert view["zalo_oa_refresh_token"]["configured"] is False
    assert view["zalo_oa_connected"] is False
    assert view["zalo_oa_access_token_expires_at"] is None


@pytest.mark.asyncio
async def test_store_oa_tokens_encrypts_trio_and_audits_connect(monkeypatch):
    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()
    iso = "2099-01-01T00:00:00+00:00"

    await service.store_oa_tokens(
        access_token="OA-ACCESS",
        refresh_token="OA-REFRESH",
        expires_at=iso,
        actor_id=actor_id,
    )

    assert db.committed
    assert service.cipher.decrypt(db.rows[ZALO_OA_ACCESS_TOKEN].encrypted_value) == "OA-ACCESS"
    assert service.cipher.decrypt(db.rows[ZALO_OA_REFRESH_TOKEN].encrypted_value) == "OA-REFRESH"
    # expiry is non-secret so admin_view can surface it without decrypting.
    assert db.rows[ZALO_OA_ACCESS_TOKEN_EXPIRES_AT].is_secret is False
    assert service.cipher.decrypt(db.rows[ZALO_OA_ACCESS_TOKEN_EXPIRES_AT].encrypted_value) == iso
    assert audits[0]["action"] == "zalo_oauth_connect"
    assert audits[0]["actor_id"] == actor_id
    assert audits[0]["payload"]["expires_at"] == iso


@pytest.mark.asyncio
async def test_store_oa_tokens_refresh_action_when_no_actor(monkeypatch):
    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())

    await service.store_oa_tokens(
        access_token="AT",
        refresh_token="RT",
        expires_at="2099-01-01T00:00:00+00:00",
        actor_id=None,  # system-initiated proactive refresh
    )

    assert audits[0]["action"] == "zalo_oauth_token_refresh"
    assert audits[0]["actor_id"] is None


@pytest.mark.asyncio
async def test_clear_zalo_oa_tokens_audits_disconnect_and_commits(monkeypatch):
    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    class _ClearDb:
        def __init__(self) -> None:
            self.committed = False
            self.executed: list = []

        async def execute(self, stmt):
            self.executed.append(stmt)

        async def commit(self):
            self.committed = True

    db = _ClearDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    await service.clear_zalo_oa_tokens(actor_id=actor_id)

    assert db.committed
    assert len(db.executed) == 1  # one DELETE covering all three keys
    assert audits[0]["action"] == "zalo_oauth_disconnect"
    assert audits[0]["payload"]["cleared_keys"] == [
        ZALO_OA_ACCESS_TOKEN,
        ZALO_OA_REFRESH_TOKEN,
        ZALO_OA_ACCESS_TOKEN_EXPIRES_AT,
    ]


@pytest.mark.asyncio
async def test_maybe_refresh_noop_without_refresh_token():
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    stored = {
        ZALO_OA_ACCESS_TOKEN_EXPIRES_AT: (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
    }

    await service._maybe_refresh_oa_token(stored)

    # Nothing to refresh -> stored untouched, no token fabricated.
    assert ZALO_OA_ACCESS_TOKEN not in stored


@pytest.mark.asyncio
async def test_maybe_refresh_noop_when_token_still_fresh():
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    stored = {
        ZALO_OA_REFRESH_TOKEN: "RT-old",
        ZALO_OA_ACCESS_TOKEN_EXPIRES_AT: future,
        ZALO_OA_ACCESS_TOKEN: "AT-current",
    }

    await service._maybe_refresh_oa_token(stored)

    assert stored[ZALO_OA_ACCESS_TOKEN] == "AT-current"  # unchanged


class _FakeOAuthClient:
    """Stands in for ZaloOAOAuthClient during the rotation test."""

    def __init__(self, app_id: str, secret_key: str, **_: object) -> None:
        self.app_id = app_id

    async def refresh(self, _refresh_token: str):
        from app.services.zalo_oa_oauth import TokenSet

        return TokenSet(access_token="AT-rotated", refresh_token="RT-rotated", expires_in=3600)


class _AsyncSessionCm:
    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncSessionFactory:
    """Replaces app.core.db.async_session; yields a fresh _WriteDb each call."""

    def __init__(self) -> None:
        self.sessions: list = []

    def __call__(self):
        session = _WriteDb()
        self.sessions.append(session)
        return _AsyncSessionCm(session)


class _FakeLockRedis:
    """Stand-in for the refresh-lock Redis (SET NX EX + DELETE)."""

    def __init__(self) -> None:
        self.locked = False
        self.delete_calls: list[str] = []

    async def set(self, _key, _value, *, ex=None, nx=None):
        self.locked = True
        return True  # always win the lock in the single-process test

    async def delete(self, key):
        self.delete_calls.append(key)
        self.locked = False


@pytest.mark.asyncio
async def test_maybe_refresh_rotates_near_expiry_token_in_isolated_session(monkeypatch):
    monkeypatch.setattr(
        "app.services.zalo_oa_oauth.ZaloOAOAuthClient", _FakeOAuthClient
    )
    factory = _FakeAsyncSessionFactory()
    monkeypatch.setattr("app.core.db.async_session", factory)
    lock_redis = _FakeLockRedis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: lock_redis)

    async def fake_record_audit(*_args, **_kwargs):
        pass

    monkeypatch.setattr(
        "app.services.integration_settings.record_audit", fake_record_audit
    )

    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    stored = {
        ZALO_OA_APP_ID: "APP123",
        ZALO_OA_SECRET_KEY: "SECRET",
        ZALO_OA_REFRESH_TOKEN: "RT-old",
        ZALO_OA_ACCESS_TOKEN: "AT-stale",
        ZALO_OA_ACCESS_TOKEN_EXPIRES_AT: expired,
    }

    await service._maybe_refresh_oa_token(stored)

    # Caller's in-memory view picks up the rotation...
    assert stored[ZALO_OA_ACCESS_TOKEN] == "AT-rotated"
    assert stored[ZALO_OA_REFRESH_TOKEN] == "RT-rotated"
    assert stored[ZALO_OA_ACCESS_TOKEN_EXPIRES_AT]  # ISO string written
    # ...persisted in an ISOLATED, committed session (not the caller's).
    assert len(factory.sessions) == 1
    assert factory.sessions[0].committed
    assert (
        service.cipher.decrypt(factory.sessions[0].rows[ZALO_OA_REFRESH_TOKEN].encrypted_value)
        == "RT-rotated"
    )
    assert lock_redis.delete_calls  # cross-turn lock always released (finally)
