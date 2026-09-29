import json
import uuid

import pytest
from pydantic import ValidationError

from app.services.integration_settings import (
    CUSTOM_LLM_API_KEY,
    CUSTOM_LLM_BASE_URL,
    CUSTOM_LLM_ENABLE,
    CUSTOM_LLM_AGENT_MODEL,
    FB_APP_ID,
    FB_APP_SECRET,
    FB_LOGIN_CONFIG_ID,
    FB_WEBHOOK_VERIFY_TOKEN,
    IntegrationSettingsCipher,
    IntegrationSettingsService,
    MINIMAX_API_KEY,
    LLM_FAILOVER_ORDER,
    normalize_llm_failover_order,
    OPENROUTER_API_KEY,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_APP_ID,
    ZALO_OA_REFRESH_LOCK_KEY,
    ZALO_OA_REFRESH_TOKEN,
    ZALO_OA_SECRET_KEY,
)
from app.services.integration_settings.providers.llm import (
    EMBEDDING_GEMINI_API_KEY,
    EMBEDDING_PROVIDER,
    LLM_AGENT_MAX_TOKENS,
    LLM_PROGRESSIVE_SEND,
    LLM_REASONING_MODE,
)


class _Settings:
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    embedding_provider = "openrouter"
    gemini_api_key = ""
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
    zalo_oa_refresh_token = ""
    zalo_bot_request_timeout = 10
    minimax_api_key = ""
    minimax_enable = True
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_extractor_model = "MiniMax-M2.5-highspeed"
    openrouter_api_key = ""
    openrouter_enable = False
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v4-flash"
    openrouter_extractor_model = "deepseek/deepseek-v4-flash"
    openrouter_digest_model = "deepseek/deepseek-v4-flash"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    embedding_dim = 3072
    llm_default_provider = "minimax"
    # Custom OpenAI-compatible failover provider (env defaults — DB overrides).
    custom_llm_enable = False
    custom_llm_label = "Dự phòng"
    custom_llm_api_key = ""
    custom_llm_base_url = ""
    custom_llm_agent_model = ""
    custom_llm_fast_model = ""
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

    async def get(self, _model, key):
        return None


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


class _MutableDb(_WriteDb):
    def __init__(self, rows=None) -> None:
        super().__init__()
        self.rows = {row.key: row for row in (rows or [])}
        self.scalars_calls = 0
        self.commit_count = 0

    async def scalars(self, _query):
        self.scalars_calls += 1
        return _ScalarResult(list(self.rows.values()))

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None, bool]] = []
        self.deleted: list[str] = []

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self._store:
            return False
        self._store[key] = value
        return "OK"

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1 if self._store.pop(key, None) is not None else 0

    async def eval(self, _script: str, _numkeys: int, *args: str) -> int:
        """Only the lock-release CAS script is exercised: delete iff owned."""
        key, owner = args[0], args[1]
        if self._store.get(key) != owner:
            return 0
        self.deleted.append(key)
        self._store.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_zalo_admin_view_reports_status_only_for_stored_refresh_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("refresh-token-for-zalo-oa")
    service = IntegrationSettingsService(
        _ReadDb([_Row(ZALO_OA_REFRESH_TOKEN, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_view()

    assert view["zalo_oa_refresh_token"] == {
        "configured": True,
        "preview": "25 ký tự",
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
        "app.services.integration_settings.providers.zalo.record_audit",
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
async def test_update_zalo_evicts_local_cache_when_redis_invalidation_fails(monkeypatch):
    async def fake_record_audit(*_args, **_kwargs):
        return None

    async def fake_bump_cache_version(_namespace: str) -> bool:
        return False

    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.record_audit",
        fake_record_audit,
    )
    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.bump_cache_version",
        fake_bump_cache_version,
    )

    redis = _FakeRedis()
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)

    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    db = _MutableDb([_Row(ZALO_OA_ACCESS_TOKEN, seed.cipher.encrypt("old-access-token"))])
    service = IntegrationSettingsService(db, settings=_Settings())

    first = await service.resolve_zalo()
    second = await service.resolve_zalo()

    assert first.oa_access_token == "old-access-token"
    assert second.oa_access_token == "old-access-token"
    assert db.scalars_calls == 1

    changed = await service.update_zalo(
        {ZALO_OA_ACCESS_TOKEN: "new-access-token"},
        actor_id=uuid.uuid4(),
    )
    refreshed = await service.resolve_zalo()

    assert changed == [ZALO_OA_ACCESS_TOKEN]
    assert refreshed.oa_access_token == "new-access-token"
    assert db.scalars_calls == 2
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_refresh_oa_access_token_persists_before_audit_and_evicts_local_cache(
    monkeypatch,
):
    async def fake_record_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    async def fake_bump_cache_version(_namespace: str) -> bool:
        return False

    class _Response:
        def __init__(self, payload: dict[str, str]) -> None:
            self._payload = payload

        def json(self) -> dict[str, str]:
            return self._payload

    class _HttpClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

        async def post(self, url: str, data: dict[str, str], headers: dict[str, str]):
            self.calls.append((url, data, headers))
            return _Response(
                {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                }
            )

    http_client = _HttpClient()
    redis = _FakeRedis()

    async def fake_get_http_client(*_args, **_kwargs):
        return http_client

    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.record_audit",
        fake_record_audit,
    )
    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.bump_cache_version",
        fake_bump_cache_version,
    )
    monkeypatch.setattr("app.core.preamble_cache.get_redis", lambda: redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr(
        "app.core.http.get_http_client",
        fake_get_http_client,
    )

    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    db = _MutableDb(
        [
            _Row(ZALO_OA_APP_ID, seed.cipher.encrypt("oa-app-id")),
            _Row(ZALO_OA_SECRET_KEY, seed.cipher.encrypt("oa-secret-key")),
            _Row(ZALO_OA_ACCESS_TOKEN, seed.cipher.encrypt("old-access-token")),
            _Row(ZALO_OA_REFRESH_TOKEN, seed.cipher.encrypt("old-refresh-token")),
        ]
    )
    service = IntegrationSettingsService(db, settings=_Settings())

    first = await service.resolve_zalo()
    second = await service.resolve_zalo()

    assert first.oa_access_token == "old-access-token"
    assert second.oa_access_token == "old-access-token"
    assert db.scalars_calls == 1

    refreshed = await service.refresh_oa_access_token()
    after = await service.resolve_zalo()

    assert refreshed == "new-access-token"
    assert after.oa_access_token == "new-access-token"
    assert after.oa_refresh_token == "new-refresh-token"
    assert (
        service.cipher.decrypt(db.rows[ZALO_OA_ACCESS_TOKEN].encrypted_value) == "new-access-token"
    )
    assert (
        service.cipher.decrypt(db.rows[ZALO_OA_REFRESH_TOKEN].encrypted_value)
        == "new-refresh-token"
    )
    assert db.commit_count == 1
    assert db.scalars_calls == 2
    assert http_client.calls == [
        (
            "https://oauth.zaloapp.com/v4/oa/access_token",
            {
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
                "app_id": "oa-app-id",
            },
            {"secret_key": "oa-secret-key"},
        )
    ]
    assert redis.deleted == [ZALO_OA_REFRESH_LOCK_KEY]


@pytest.mark.asyncio
async def test_minimax_admin_view_reports_status_only_for_stored_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("sk-minimax-secret-token")
    service = IntegrationSettingsService(
        _ReadDb([_Row(MINIMAX_API_KEY, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_minimax_view()

    assert view["minimax_api_key"] == {
        "configured": True,
        "preview": "23 ký tự",
    }
    assert view["minimax_base_url"] == "https://api.minimax.io/v1"
    assert view["minimax_agent_model"] == "MiniMax-M2.7-highspeed"
    assert view["minimax_enable"] is True
    assert view["llm_default_provider"] == "minimax"
    # Nothing stored → the canonical ranking that reproduces the historic
    # failover order (other first-class provider, then the custom slot).
    assert view["llm_failover_order"] == ["minimax", "openrouter", "custom"]


@pytest.mark.asyncio
async def test_update_minimax_stores_failover_order_as_csv(monkeypatch):
    async def fake_record_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.providers.llm.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())

    changed = await service.update_minimax(
        {"llm_failover_order": ["custom", "openrouter", "minimax"]},
        actor_id=uuid.uuid4(),
    )

    assert changed == [LLM_FAILOVER_ORDER]
    assert db.rows[LLM_FAILOVER_ORDER].encrypted_value == "custom,openrouter,minimax"
    assert db.rows[LLM_FAILOVER_ORDER].is_secret is False


@pytest.mark.asyncio
async def test_admin_view_reads_stored_failover_order():
    service = IntegrationSettingsService(
        _ReadDb([_Row(LLM_FAILOVER_ORDER, "custom,openrouter")]),
        settings=_Settings(),
    )

    view = await service.admin_minimax_view()

    # The default provider always opens the turn regardless of its rank here;
    # the stored order ranks only the spares the operator cared to order.
    assert view["llm_failover_order"] == ["custom", "openrouter", "minimax"]


@pytest.mark.asyncio
async def test_minimax_resolves_llm_knob_defaults_when_nothing_stored():
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())

    cfg = await service.resolve_minimax()
    assert cfg.reasoning_mode == "off"
    assert cfg.agent_max_tokens == 0
    assert cfg.progressive_send is True

    view = await service.admin_minimax_view()
    assert view["llm_reasoning_mode"] == "off"
    assert view["llm_agent_max_tokens"] == 0
    assert view["llm_progressive_send"] is True


@pytest.mark.asyncio
async def test_minimax_stored_llm_knobs_override_defaults():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    service = IntegrationSettingsService(
        _ReadDb(
            [
                _Row(LLM_REASONING_MODE, seed.cipher.encrypt("low")),
                _Row(LLM_AGENT_MAX_TOKENS, seed.cipher.encrypt("512")),
                _Row(LLM_PROGRESSIVE_SEND, seed.cipher.encrypt("true")),
            ]
        ),
        settings=_Settings(),
    )

    cfg = await service.resolve_minimax()

    assert cfg.reasoning_mode == "low"
    assert cfg.agent_max_tokens == 512
    assert cfg.progressive_send is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("0", 0),  # 0 means "no cap" and must survive resolution untouched
        ("-5", 0),  # a malformed/negative row falls back to the no-cap default
        ("not-a-number", 0),
    ],
)
async def test_minimax_agent_max_tokens_edge_stored_values(stored, expected):
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    service = IntegrationSettingsService(
        _ReadDb([_Row(LLM_AGENT_MAX_TOKENS, seed.cipher.encrypt(stored))]),
        settings=_Settings(),
    )

    cfg = await service.resolve_minimax()

    assert cfg.agent_max_tokens == expected


@pytest.mark.asyncio
async def test_minimax_schemas_round_trip_llm_knobs():
    from app.schemas.integrations import (
        MinimaxIntegrationSettingsOut,
        MinimaxIntegrationSettingsUpdate,
    )

    update = MinimaxIntegrationSettingsUpdate(
        llm_reasoning_mode="low", llm_agent_max_tokens=0, llm_progressive_send=True
    )
    assert update.model_dump(exclude_unset=True) == {
        "llm_reasoning_mode": "low",
        "llm_agent_max_tokens": 0,
        "llm_progressive_send": True,
    }
    with pytest.raises(ValidationError):
        MinimaxIntegrationSettingsUpdate(llm_agent_max_tokens=-1)

    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    out = MinimaxIntegrationSettingsOut.model_validate(await service.admin_minimax_view())
    assert out.llm_reasoning_mode == "off"
    assert out.llm_agent_max_tokens == 0
    assert out.llm_progressive_send is True


@pytest.mark.asyncio
async def test_update_minimax_llm_knobs_bump_the_llm_client_cache_namespace(monkeypatch):
    async def fake_record_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.providers.llm.record_audit",
        fake_record_audit,
    )
    bumped: list[str] = []
    evicted: list[str] = []

    async def fake_bump_cache_version(namespace: str) -> bool:
        bumped.append(namespace)
        return True

    monkeypatch.setattr(
        "app.services.integration_settings.storage.bump_cache_version",
        fake_bump_cache_version,
    )
    monkeypatch.setattr(
        "app.services.integration_settings.storage.evict_local_namespace",
        lambda namespace: evicted.append(namespace),
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())

    changed = await service.update_minimax(
        {"llm_reasoning_mode": "low", "llm_agent_max_tokens": 512},
        actor_id=uuid.uuid4(),
    )

    assert changed == [LLM_REASONING_MODE, LLM_AGENT_MAX_TOKENS]
    # build_cached_clients keys on cache_version("integration_minimax").
    assert bumped == ["integration_minimax"]
    assert evicted == ["integration_minimax"]
    assert db.rows[LLM_AGENT_MAX_TOKENS].encrypted_value == "512"
    assert db.rows[LLM_AGENT_MAX_TOKENS].is_secret is False


@pytest.mark.asyncio
async def test_client_cache_threads_resolved_llm_knobs_into_agent_client(monkeypatch):
    from app.graph import client_cache

    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    rows = [
        _Row(LLM_REASONING_MODE, seed.cipher.encrypt("low")),
        _Row(LLM_AGENT_MAX_TOKENS, seed.cipher.encrypt("512")),
    ]

    captured: dict = {}

    def _capture_chat_for_role(role, **kwargs):
        captured["role"] = role
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(client_cache, "_chat_for_role", _capture_chat_for_role)
    monkeypatch.setattr(client_cache, "build_embedder", lambda *a, **k: object())
    monkeypatch.setattr(client_cache, "get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.factories._build_fast_llm", lambda **k: None)
    monkeypatch.setattr("app.graph.factories._build_failover_chain", lambda **k: [])

    client_cache.reset_client_cache()
    try:
        await client_cache.build_cached_clients(_ReadDb(rows))
    finally:
        client_cache.reset_client_cache()

    assert captured["role"] == "agent"
    assert captured["reasoning_mode"] == "low"
    assert captured["max_tokens"] == 512


def test_normalize_failover_order_drops_unknown_and_fills_canonically():
    assert normalize_llm_failover_order("custom,bogus,custom") == (
        "custom",
        "minimax",
        "openrouter",
    )
    assert normalize_llm_failover_order(["openrouter"]) == (
        "openrouter",
        "minimax",
        "custom",
    )
    assert normalize_llm_failover_order(None) == ("minimax", "openrouter", "custom")
    assert normalize_llm_failover_order("  openrouter , minimax  ") == (
        "openrouter",
        "minimax",
        "custom",
    )


@pytest.mark.asyncio
async def test_update_minimax_encrypts_token_and_audits_key_names(monkeypatch):
    audits = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.providers.llm.record_audit",
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
        "app.services.integration_settings.providers.llm.record_audit",
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
async def test_openrouter_admin_view_reports_status_only_for_stored_token():
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    encrypted = seed.cipher.encrypt("sk-or-v1-openrouter-secret-token")
    service = IntegrationSettingsService(
        _ReadDb([_Row(OPENROUTER_API_KEY, encrypted)]),
        settings=_Settings(),
    )

    view = await service.admin_openrouter_view()

    assert view["openrouter_api_key"] == {
        "configured": True,
        "preview": "32 ký tự",
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
        "app.services.integration_settings.providers.llm.record_audit",
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


@pytest.mark.asyncio
async def test_resolve_embedding_defaults_to_openrouter_without_stored_values():
    service = IntegrationSettingsService(
        _ReadDb([]),
        settings=_Settings(),
    )

    embedding = await service.resolve_embedding()

    assert embedding.provider == "openrouter"
    assert embedding.openrouter_api_key == ""
    assert embedding.gemini_api_key == ""


@pytest.mark.asyncio
async def test_resolve_embedding_prefers_stored_provider_and_gemini_key():
    service = IntegrationSettingsService(
        _ReadDb(
            [
                _Row("embedding_provider", "gemini"),
                _Row("embedding_gemini_api_key", "gemini-stored-key"),
            ]
        ),
        settings=_Settings(),
    )

    embedding = await service.resolve_embedding()

    assert embedding.provider == "gemini"
    assert embedding.gemini_api_key == "gemini-stored-key"


@pytest.mark.asyncio
async def test_resolve_embedding_falls_back_when_stored_provider_is_unknown():
    service = IntegrationSettingsService(
        _ReadDb([_Row("embedding_provider", "ollama")]),
        settings=_Settings(),
    )

    embedding = await service.resolve_embedding()

    assert embedding.provider == "openrouter"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_update_openrouter_stores_embedding_provider_and_secret_key(monkeypatch):
    audits: list[dict] = []

    async def fake_record_audit(db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.providers.llm.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_openrouter(
        {
            "embedding_provider": "gemini",
            "embedding_gemini_api_key": "gemini-new-key",
        },
        actor_id=actor_id,
    )

    assert changed == ["embedding_provider", "embedding_gemini_api_key"]
    assert db.committed
    stored_provider = db.rows[EMBEDDING_PROVIDER]
    assert stored_provider.encrypted_value == "gemini"
    stored_key = db.rows[EMBEDDING_GEMINI_API_KEY]
    assert stored_key.encrypted_value.startswith("v1:")
    assert "gemini-new-key" not in stored_key.encrypted_value
    assert service.cipher.decrypt(stored_key.encrypted_value) == "gemini-new-key"
    assert audits == [
        {
            "action": "update_openrouter_integration_settings",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "openrouter",
            "payload": {
                "changed_keys": ["embedding_provider", "embedding_gemini_api_key"]
            },
        }
    ]


# ─── Custom OpenAI-compatible failover provider ─────────────────────────────


@pytest.mark.asyncio
async def test_custom_llm_admin_view_is_unconfigured_without_env_or_db():
    service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())

    view = await service.admin_custom_llm_view()

    assert view["custom_llm_api_key"] == {"configured": False, "preview": None}
    assert view["custom_llm_base_url"] == ""
    assert view["custom_llm_agent_model"] == ""
    assert view["custom_llm_fast_model"] == ""
    assert view["custom_llm_usable"] is False
    assert view["custom_llm_enable"] is False
    assert view["llm_default_provider"] == "minimax"
    assert view["last_test"] is None


@pytest.mark.asyncio
async def test_custom_llm_admin_view_env_fallback_and_usable():
    class _CustomSettings(_Settings):
        custom_llm_enable = True
        custom_llm_api_key = "sk-mimo-secret-token"
        custom_llm_base_url = "https://api.xiaomi.example/v1"
        custom_llm_agent_model = "mimo-7b"
        custom_llm_fast_model = ""

    service = IntegrationSettingsService(_ReadDb([]), settings=_CustomSettings())

    view = await service.admin_custom_llm_view()

    assert view["custom_llm_api_key"] == {"configured": True, "preview": "20 ký tự"}
    assert view["custom_llm_base_url"] == "https://api.xiaomi.example/v1"
    assert view["custom_llm_agent_model"] == "mimo-7b"
    # Blank fast model inherits the agent model: one model id is enough.
    assert view["custom_llm_usable"] is True


@pytest.mark.asyncio
async def test_custom_llm_db_rows_override_env_and_fall_back_to_agent_model():
    class _CustomSettings(_Settings):
        custom_llm_enable = False
        custom_llm_api_key = ""
        custom_llm_base_url = "https://env.example/v1"

    service = IntegrationSettingsService(
        _ReadDb(
            [
                _Row(CUSTOM_LLM_ENABLE, "true"),
                _Row(CUSTOM_LLM_API_KEY, IntegrationSettingsService(_ReadDb([]), settings=_Settings()).cipher.encrypt("sk-db-only-key")),
                _Row(CUSTOM_LLM_BASE_URL, "https://api.xiaomi.example/v1"),
                _Row(CUSTOM_LLM_AGENT_MODEL, "mimo-7b"),
            ]
        ),
        settings=_CustomSettings(),
    )

    cfg = await service.resolve_custom_llm()

    assert cfg.enabled is True
    assert cfg.api_key == "sk-db-only-key"
    # DB base_url wins over the env value.
    assert cfg.base_url == "https://api.xiaomi.example/v1"
    assert cfg.usable is True


@pytest.mark.asyncio
async def test_update_custom_llm_encrypts_key_and_audits(monkeypatch):
    audits = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.providers.llm.record_audit",
        fake_record_audit,
    )

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()

    changed = await service.update_custom_llm(
        {
            "custom_llm_api_key": " sk-mimo-secret-token ",
            "custom_llm_base_url": "https://api.xiaomi.example/v1",
            "custom_llm_enable": True,
        },
        actor_id=actor_id,
    )

    assert changed == [
        "custom_llm_api_key",
        "custom_llm_base_url",
        "custom_llm_enable",
    ]
    assert db.committed
    stored = db.rows[CUSTOM_LLM_API_KEY]
    assert stored.encrypted_value.startswith("v1:")
    assert "sk-mimo-secret-token" not in stored.encrypted_value
    assert service.cipher.decrypt(stored.encrypted_value) == "sk-mimo-secret-token"
    # Non-secret fields are stored as plaintext values.
    assert db.rows[CUSTOM_LLM_BASE_URL].encrypted_value == "https://api.xiaomi.example/v1"
    assert db.rows[CUSTOM_LLM_ENABLE].is_secret is False
    assert audits == [
        {
            "action": "update_custom_llm_integration_settings",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "fallback_llm",
            "payload": {"changed_keys": [
                "custom_llm_api_key",
                "custom_llm_base_url",
                "custom_llm_enable",
            ]},
        }
    ]


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
async def test_facebook_oauth_admin_view_reports_status_only_for_secrets_and_surfaces_plaintext():
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
    # Authorizing secrets report status only — never characters of the value.
    assert view["facebook_app_secret"] == {
        "configured": True,
        "preview": "16 ký tự",
    }
    assert view["facebook_webhook_verify_token"] == {
        "configured": True,
        "preview": "20 ký tự",
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

    monkeypatch.setattr("app.services.integration_settings.providers.facebook.record_audit", fake_record_audit)

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

    monkeypatch.setattr("app.services.integration_settings.providers.facebook.record_audit", fake_record_audit)

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


# ─── SEC-07: admin views must not leak any character of a stored secret ─────

# Every authorizing secret seeded with a distinct 24-char hex value: a leaked
# character window is unmistakable against the surrounding JSON.
_SECRET_PROBES = {
    "zalo_bot_token": "a1b2c3d4e5f60718293a4b5c",
    "zalo_bot_webhook_secret": "7f6e5d4c3b2a1908f7e6d5c4",
    "zalo_oa_secret_key": "2c4d6e8fa0b1c2d3e4f50617",
    "zalo_oa_access_token": "93b7c1d5e9f3072b4a6c8e0d",
    "zalo_oa_refresh_token": "5e1f7a3c9b2d4f6082a4c6e8",
    "minimax_api_key": "c8d0e2f4a6b8c0d2e4f6a8b0",
    "openrouter_api_key": "3a5c7e9b1d3f5072a4c6e8b0",
    "custom_llm_api_key": "f1e2d3c4b5a69788796a5b4c",
    "jev_api_key": "0d1e2f3a4b5c6d7e8f901234",
    "facebook_app_secret": "4b8a2c6e0f1d3b5a7c9e0d2f",
    "facebook_webhook_verify_token": "6a4c2e0f8b6d4a2c0e8f6d4b",
}


@pytest.mark.asyncio
async def test_admin_views_leak_no_character_of_a_stored_secret():
    """SEC-07: an admin GET may say a secret is configured, never leak it.

    The old ``first4...last4`` preview leaked eight characters of every
    credential. Every authorizing secret is seeded and every admin view is
    scanned for ANY 4-character window of those values, so a partial-preview
    regression fails here rather than shipping.
    """
    seed = IntegrationSettingsService(_ReadDb([]), settings=_Settings())
    rows = [_Row(key, seed.cipher.encrypt(value)) for key, value in _SECRET_PROBES.items()]
    service = IntegrationSettingsService(_ReadDb(rows), settings=_Settings())
    empty_service = IntegrationSettingsService(_ReadDb([]), settings=_Settings())

    async def _all_views(source) -> dict:
        return {
            "zalo": await source.admin_view(),
            "minimax": await source.admin_minimax_view(),
            "openrouter": await source.admin_openrouter_view(),
            "custom_llm": await source.admin_custom_llm_view(),
            "jev": await source.admin_jev_view(),
            "facebook": await source.admin_facebook_oauth_view(),
        }

    views = await _all_views(service)
    # The same views with nothing configured: any window that also appears here
    # is the view's own fixed text (base URLs, model ids, 3072), not a leak.
    baseline = json.dumps(await _all_views(empty_service), ensure_ascii=False, default=str)

    for name, view in views.items():
        payload = json.dumps(view, ensure_ascii=False, default=str)
        for key, value in _SECRET_PROBES.items():
            assert value not in payload, f"{name} leaked the whole value of {key}"
            for start in range(len(value) - 3):
                window = value[start : start + 4]
                if window in baseline:
                    continue
                assert window not in payload, f"{name} leaked {window!r} of {key}"

    # The projection is status-only: configured + length, same field name the
    # admin UI renders as the field placeholder.
    status_only = {"configured": True, "preview": "24 ký tự"}
    assert views["zalo"]["zalo_bot_token"] == status_only
    assert views["zalo"]["zalo_bot_webhook_secret"] == status_only
    assert views["zalo"]["zalo_oa_secret_key"] == status_only
    assert views["zalo"]["zalo_oa_access_token"] == status_only
    assert views["zalo"]["zalo_oa_refresh_token"] == status_only
    assert views["minimax"]["minimax_api_key"] == status_only
    assert views["openrouter"]["openrouter_api_key"] == status_only
    assert views["custom_llm"]["custom_llm_api_key"] == status_only
    assert views["jev"]["jev_api_key"] == status_only
    assert views["facebook"]["facebook_app_secret"] == status_only
    assert views["facebook"]["facebook_webhook_verify_token"] == status_only


@pytest.mark.asyncio
async def test_reveal_facebook_oauth_requires_the_actors_password(monkeypatch):
    """SEC-07: reveal is step-up gated and audited; a bad password reveals nothing."""
    from app.core.security import hash_password_sync
    from app.shared.domain.errors import BadRequestError

    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr("app.services.integration_settings.providers.facebook.record_audit", fake_record_audit)

    db = _WriteDb()
    service = IntegrationSettingsService(db, settings=_Settings())
    actor_id = uuid.uuid4()
    password_hash = hash_password_sync("correct horse battery staple")

    with pytest.raises(BadRequestError):
        await service.reveal_facebook_oauth(
            actor_id=actor_id,
            password="wrong password",
            password_hash=password_hash,
        )
    assert audits == []
    assert db.committed is False

    cfg = await service.reveal_facebook_oauth(
        actor_id=actor_id,
        password="correct horse battery staple",
        password_hash=password_hash,
    )

    assert cfg.app_secret == ""
    assert db.committed is True
    assert audits == [
        {
            "action": "reveal_facebook_credentials",
            "actor_id": actor_id,
            "target_type": "integration_settings",
            "target_id": "facebook",
            "payload": {"revealed": []},
        }
    ]


@pytest.mark.asyncio
async def test_reveal_facebook_oauth_rejects_a_missing_password_hash(monkeypatch):
    """An admin principal without a password hash (never a real login) fails closed."""
    from app.shared.domain.errors import BadRequestError

    service = IntegrationSettingsService(_WriteDb(), settings=_Settings())

    with pytest.raises(BadRequestError):
        await service.reveal_facebook_oauth(
            actor_id=uuid.uuid4(),
            password="anything",
            password_hash="",
        )
