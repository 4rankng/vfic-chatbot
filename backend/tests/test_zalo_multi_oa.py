"""Multi-OA: oa_id routing, per-account credentials, and the link lifecycle.

The original OA stays the fallback for anything the router cannot attribute, so
a single-OA deployment behaves exactly as before: these tests pin both the new
routing and the unchanged fallback.
"""

from __future__ import annotations

import types

import pytest

from app.channels import types as ct
from app.channels.providers import zalo_account as zalo_account_mod
from app.channels.providers.zalo_account import (
    ZaloOaAccountInvalidError,
    ZaloOaAccountLifecycle,
    ZaloOaAccountNotFoundError,
    ZaloOaAccountResolver,
    validate_oa_id,
)
from app.channels.providers.zalo_oa import ZaloOAChannelAdapter
from app.core.config import Settings
from app.models.channel_account import ChannelAccount
from app.services.integration_settings import IntegrationSettingsService
from app.services.integration_settings.providers.zalo import (
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_APP_ID,
    ZALO_OA_ACCOUNT_SETTING_BASES,
    ZALO_OA_DEFAULT_ACCOUNT_KEY,
    ZALO_OA_REFRESH_TOKEN,
    ZALO_OA_SECRET_KEY,
    is_oa_account_setting_key,
    oa_account_setting_key,
)
from app.services.zalo_oa_events import oa_id_from_payload

SECOND_OA_ID = "987654321098765"


def _account(account_key: str, *, status: str = "ACTIVE") -> ChannelAccount:
    row = ChannelAccount(
        provider=ct.PROVIDER_ZALO_OA,
        account_key=account_key,
        label=f"OA {account_key}",
        status=status,
        generation=1,
    )
    return row


class _ScalarSession:
    """Minimal session double: one canned ``scalar`` row per call."""

    def __init__(self, rows) -> None:
        self._rows = list(rows)
        self.added: list[object] = []
        self.commits = 0
        self.rolled_back = 0

    async def scalar(self, _stmt):
        return self._rows.pop(0) if self._rows else None

    async def execute(self, _stmt):
        return types.SimpleNamespace(rowcount=1)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def refresh(self, _obj) -> None:
        return None


class _StoredSettings(IntegrationSettingsService):
    """Settings service whose stored rows come from a dict (no DB, no cipher)."""

    def __init__(self, stored: dict[str, str]) -> None:
        self.settings = Settings(
            app_env="development",
            zalo_oa_app_id="env-app",
            zalo_oa_secret_key="env-secret",
            zalo_oa_access_token="env-access",
            zalo_oa_refresh_token="env-refresh",
        )
        self.cipher = None
        self._stored = dict(stored)
        self.writes: list[tuple[str, str]] = []

    async def _stored_values(self, keys):
        wanted = set(keys)
        return {k: v for k, v in self._stored.items() if k in wanted}

    async def _write_secret(self, key, value, *, actor_id=None):  # type: ignore[override]
        if value is None:
            return False
        self.writes.append((key, value))
        return True


# ---------------------------------------------------------------------------
# oa_id extraction and routing
# ---------------------------------------------------------------------------


def test_oa_id_reads_root_then_recipient():
    assert oa_id_from_payload({"oa_id": SECOND_OA_ID}) == SECOND_OA_ID
    assert oa_id_from_payload({"recipient": {"id": "555"}}) == "555"
    assert oa_id_from_payload({"recipient_id": "777"}) == "777"
    assert oa_id_from_payload({"sender": {"id": "user-1"}}) is None
    assert oa_id_from_payload({"oa_id": ""}) is None


async def test_a_linked_active_oa_routes_to_its_own_account_key():
    db = _ScalarSession([_account(SECOND_OA_ID)])
    resolver = ZaloOaAccountResolver(db)  # type: ignore[arg-type]

    key = await resolver.account_key_for_payload({"oa_id": SECOND_OA_ID})

    assert key == SECOND_OA_ID


async def test_unknown_or_absent_oa_id_falls_back_to_the_default_account():
    for payload in ({"oa_id": "999"}, {"event_name": "follow", "follower": {"id": "u"}}):
        db = _ScalarSession([None])
        resolver = ZaloOaAccountResolver(db)  # type: ignore[arg-type]
        assert await resolver.account_key_for_payload(payload) == ZALO_OA_DEFAULT_ACCOUNT_KEY


async def test_an_unlinked_oa_falls_back_to_the_default_account():
    db = _ScalarSession([_account(SECOND_OA_ID, status="INACTIVE")])
    resolver = ZaloOaAccountResolver(db)  # type: ignore[arg-type]

    assert await resolver.account_key_for_payload({"oa_id": SECOND_OA_ID}) == (
        ZALO_OA_DEFAULT_ACCOUNT_KEY
    )


def test_oa_id_validation_rejects_malformed_and_reserved():
    assert validate_oa_id(" 12345 ") == "12345"
    assert is_oa_account_setting_key(oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, "123"))
    assert not is_oa_account_setting_key(ZALO_OA_ACCESS_TOKEN)
    assert not is_oa_account_setting_key("zalo_bot_token:123")
    for bad in ("", "   ", "abc", "12a", ZALO_OA_DEFAULT_ACCOUNT_KEY, "9" * 65):
        with pytest.raises(ZaloOaAccountInvalidError):
            validate_oa_id(bad)


# ---------------------------------------------------------------------------
# Per-account credential resolution
# ---------------------------------------------------------------------------


async def test_a_second_oa_resolves_its_own_credentials():
    service = _StoredSettings(
        {
            oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, SECOND_OA_ID): "second-access",
            oa_account_setting_key(ZALO_OA_SECRET_KEY, SECOND_OA_ID): "second-secret",
            oa_account_setting_key(ZALO_OA_APP_ID, SECOND_OA_ID): "second-app",
            oa_account_setting_key(ZALO_OA_REFRESH_TOKEN, SECOND_OA_ID): "second-refresh",
        }
    )

    cfg = await service.resolve_zalo(SECOND_OA_ID)

    assert cfg.oa_access_token == "second-access"
    assert cfg.oa_secret_key == "second-secret"
    assert cfg.oa_app_id == "second-app"
    assert cfg.oa_refresh_token == "second-refresh"


async def test_a_second_oa_never_inherits_the_original_oa_token():
    # Nothing stored for the second OA: it must resolve empty rather than send
    # with the original OA's token (a reply leaving as the wrong brand).
    service = _StoredSettings({ZALO_OA_ACCESS_TOKEN: "original-access"})

    cfg = await service.resolve_zalo(SECOND_OA_ID)

    assert cfg.oa_access_token == ""
    assert cfg.oa_refresh_token == ""


async def test_the_default_account_still_resolves_singletons_and_env():
    service = _StoredSettings({ZALO_OA_ACCESS_TOKEN: "stored-access"})

    cfg = await service.resolve_zalo()

    assert cfg.oa_access_token == "stored-access"
    assert cfg.oa_secret_key == "env-secret"
    assert (await service.resolve_zalo(ZALO_OA_DEFAULT_ACCOUNT_KEY)).oa_access_token == (
        "stored-access"
    )


# ---------------------------------------------------------------------------
# Link lifecycle
# ---------------------------------------------------------------------------


async def test_link_registers_the_account_and_stores_namespaced_credentials(monkeypatch):
    db = _ScalarSession([None])
    written: list[tuple[str, dict]] = []

    async def _write(self, account_key, values, *, actor_id=None):
        written.append((account_key, dict(values)))
        return list(values)

    audited: list[dict] = []

    async def _audit(_db, **kwargs):
        audited.append(kwargs)

    monkeypatch.setattr(
        IntegrationSettingsService, "write_oa_account_credentials", _write, raising=True
    )
    monkeypatch.setattr(zalo_account_mod, "record_audit", _audit)

    row = await ZaloOaAccountLifecycle(db).link(  # type: ignore[arg-type]
        oa_id=SECOND_OA_ID,
        label="Ting Ting Software Solution",
        credentials={
            ZALO_OA_ACCESS_TOKEN: "second-access",
            ZALO_OA_SECRET_KEY: "second-secret",
            ZALO_OA_REFRESH_TOKEN: "",
        },
        actor_id="admin-1",
    )

    assert row.provider == ct.PROVIDER_ZALO_OA
    assert row.account_key == SECOND_OA_ID
    assert row.status == "ACTIVE"
    assert row.generation == 1
    assert row.label == "Ting Ting Software Solution"
    assert written == [
        (
            SECOND_OA_ID,
            {
                ZALO_OA_ACCESS_TOKEN: "second-access",
                ZALO_OA_SECRET_KEY: "second-secret",
                ZALO_OA_REFRESH_TOKEN: "",
            },
        )
    ]
    assert db.commits == 1
    assert audited[0]["action"] == "link_zalo_oa_account"
    assert audited[0]["target_id"] == SECOND_OA_ID


class _FakeSettingsService:
    """Settings double: a resolvable original-OA token and no-op writes."""

    default_access_token = ""

    def __init__(self, _db) -> None:
        self.writes: list[tuple[str, dict]] = []

    async def resolve_zalo(self, account_key=None):
        return types.SimpleNamespace(oa_access_token=type(self).default_access_token)

    async def write_oa_account_credentials(self, account_key, values, *, actor_id=None):
        self.writes.append((account_key, dict(values)))
        return list(values)

    async def clear_oa_account_credentials(self, account_key):
        return 0


def _use_fake_settings(monkeypatch, *, default_access_token: str = ""):
    import app.services.integration_settings as settings_pkg

    _FakeSettingsService.default_access_token = default_access_token
    monkeypatch.setattr(settings_pkg, "IntegrationSettingsService", _FakeSettingsService)


async def test_relinking_bumps_the_generation_of_an_inactive_account(monkeypatch):
    existing = _account(SECOND_OA_ID, status="INACTIVE")
    db = _ScalarSession([existing])
    _use_fake_settings(monkeypatch)

    row = await ZaloOaAccountLifecycle(db).link(  # type: ignore[arg-type]
        oa_id=SECOND_OA_ID,
        label="",
        credentials={ZALO_OA_ACCESS_TOKEN: "second-access"},
    )

    assert row is existing
    assert row.status == "ACTIVE"
    assert row.generation == 2


async def test_link_requires_an_access_token(monkeypatch):
    db = _ScalarSession([None])
    _use_fake_settings(monkeypatch)

    with pytest.raises(ZaloOaAccountInvalidError):
        await ZaloOaAccountLifecycle(db).link(  # type: ignore[arg-type]
            oa_id=SECOND_OA_ID,
            label="",
            credentials={ZALO_OA_SECRET_KEY: "second-secret"},
        )

    assert db.added == []


async def test_unlink_deactivates_and_clears_credentials(monkeypatch):
    row = _account(SECOND_OA_ID)
    db = _ScalarSession([row])
    cleared: list[str] = []

    async def _clear(self, account_key):
        cleared.append(account_key)
        return len(ZALO_OA_ACCOUNT_SETTING_BASES)

    monkeypatch.setattr(
        IntegrationSettingsService, "clear_oa_account_credentials", _clear, raising=True
    )

    await ZaloOaAccountLifecycle(db).unlink(SECOND_OA_ID, actor_id="admin-1")  # type: ignore[arg-type]

    assert row.status == "INACTIVE"
    assert row.generation == 2
    assert cleared == [SECOND_OA_ID]
    assert db.commits == 1


async def test_unlink_refuses_the_default_account_and_unknown_oa():
    with pytest.raises(ZaloOaAccountNotFoundError):
        await ZaloOaAccountLifecycle(_ScalarSession([None])).unlink(  # type: ignore[arg-type]
            SECOND_OA_ID
        )
    with pytest.raises(ZaloOaAccountInvalidError):
        await ZaloOaAccountLifecycle(_ScalarSession([_account(ZALO_OA_DEFAULT_ACCOUNT_KEY)])).unlink(  # type: ignore[arg-type]
            ZALO_OA_DEFAULT_ACCOUNT_KEY
        )


# ---------------------------------------------------------------------------
# Adapter / receipt scoping
# ---------------------------------------------------------------------------


def test_receipts_are_scoped_to_the_adapter_account():
    adapter = ZaloOAChannelAdapter(sender=object(), account_key=SECOND_OA_ID)

    receipt = adapter.parse_receipt(
        {
            "event_name": "user_seen_message",
            "message": {"msg_id": "m-1"},
        }
    )

    assert receipt is not None
    assert receipt.account_key == SECOND_OA_ID
    assert ZaloOAChannelAdapter(sender=object()).parse_receipt(
        {"event_name": "user_seen_message", "message": {"msg_id": "m-2"}}
    ).account_key == ZALO_OA_DEFAULT_ACCOUNT_KEY


# ---------------------------------------------------------------------------
# Ingress / outbound routing
# ---------------------------------------------------------------------------


async def test_handle_scopes_the_conversation_to_the_receiving_oa(monkeypatch):
    import uuid as _uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(
        id=_uuid.uuid4(), zalo_chat_id="oa:user-1", zalo_channel="oa", version=1, mode="BOT"
    )
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.record_inbound = AsyncMock()
    svc.get = AsyncMock(return_value=conv)
    svc.run_start_guard = MagicMock(return_value=True)
    svc.acquire_lock = AsyncMock(return_value=_uuid.uuid4())
    svc.release_lock = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)
    monkeypatch.setattr(
        "app.services.webhook.MessageDedupService.claim", AsyncMock(return_value=True)
    )
    db = MagicMock()
    db.refresh = AsyncMock()

    enrich: list[dict] = []

    result = await ZaloWebhookService.handle(
        db,
        {
            "event_name": "user_send_text",
            "sender": {"id": "user-1"},
            "message": {"text": "Xin chào", "msg_id": "m-1"},
        },
        enqueue=lambda _job: True,
        channel="oa",
        account_key=SECOND_OA_ID,
        enrich_oa_profile=enrich.append,
    )

    assert result["status"] == "processing"
    assert svc.ensure.await_args.kwargs["account_key"] == SECOND_OA_ID
    # The enrichment must authenticate as the same OA, never the original one.
    assert enrich[0]["account_key"] == SECOND_OA_ID


async def test_side_events_are_scoped_to_the_receiving_oa(monkeypatch):
    import uuid as _uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.webhook import ZaloWebhookService

    conv = SimpleNamespace(id=_uuid.uuid4(), zalo_chat_id="oa:user-1", zalo_channel="oa")
    svc = MagicMock()
    svc.ensure = AsyncMock(return_value=conv)
    svc.apply_follow = AsyncMock()
    monkeypatch.setattr("app.services.webhook.ConversationService", lambda db: svc)

    result = await ZaloWebhookService.handle(  # type: ignore[arg-type]
        MagicMock(),
        {"event_name": "follow", "follower": {"id": "user-1"}, "oa_id": SECOND_OA_ID},
        enqueue=lambda _job: True,
        channel="oa",
        account_key=SECOND_OA_ID,
    )

    assert result == {"status": "follow"}
    assert svc.ensure.await_args.kwargs["account_key"] == SECOND_OA_ID


class _MessageSession:
    """Session double returning one (provider, account_key) row for the join."""

    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, _stmt):
        return types.SimpleNamespace(first=lambda: self._row)


async def test_the_outbox_resolves_the_conversation_oa():
    from app.services.outbox.dispatcher import _zalo_account_key_for_message

    row = types.SimpleNamespace(provider=ct.PROVIDER_ZALO_OA, account_key=SECOND_OA_ID)
    assert await _zalo_account_key_for_message(_MessageSession(row), 7) == SECOND_OA_ID
    bot = types.SimpleNamespace(provider=ct.PROVIDER_ZALO_BOT, account_key="default:zalo_bot")
    assert await _zalo_account_key_for_message(_MessageSession(bot), 7) is None
    assert await _zalo_account_key_for_message(_MessageSession(None), 7) is None
    assert await _zalo_account_key_for_message(_MessageSession(row), None) is None


async def test_a_second_oa_dispatch_carries_its_own_account_key(monkeypatch):
    """The command sent for a second OA must not be stamped with the default."""
    from app.services.outbox import dispatcher as dispatcher_mod

    captured: dict = {}

    class _Dispatch:
        def __init__(self, _registry) -> None:
            pass

        async def send(self, command):
            captured["command"] = command
            return types.SimpleNamespace(
                ok=True,
                provider_message_id="m-1",
                error=None,
                error_class=None,
                suppressed=False,
                telemetry=None,
            )

    def _fake_registry(cfg, *, oa_refresh=None, oa_account_key=""):
        captured["oa_account_key"] = oa_account_key
        return types.SimpleNamespace(get=lambda _provider: object())

    monkeypatch.setattr(dispatcher_mod, "ChannelDispatchService", _Dispatch, raising=False)
    monkeypatch.setattr(
        "app.channels.dispatch.ChannelDispatchService", _Dispatch, raising=False
    )
    monkeypatch.setattr(
        "app.channels.dispatch.build_zalo_registry_from_config", _fake_registry
    )

    candidate = types.SimpleNamespace(
        channel="zalo_oa",
        message_id=1,
        outbox_id=2,
        payload={"chat_id": "oa:user-1", "text": "Xin chào", "quote_message_id": "m-0"},
    )
    outbox = types.SimpleNamespace(channel_account_generation=1)
    result = await dispatcher_mod._try_neutral_dispatch(
        None, candidate, outbox, object(), object(), None, account_key=SECOND_OA_ID
    )

    assert result is not None and result.ok is True
    assert captured["oa_account_key"] == SECOND_OA_ID
    assert captured["command"].account_key == SECOND_OA_ID


# ---------------------------------------------------------------------------
# Per-account token refresh
# ---------------------------------------------------------------------------


class _CommitOnly:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Redis:
    def __init__(self) -> None:
        self.locks: list[str] = []
        self.evals: list[tuple] = []

    async def set(self, key, value, **_kwargs):
        self.locks.append(key)
        return True

    async def eval(self, *args):
        self.evals.append(args)
        return 1


def _refresh_harness(monkeypatch, redis: _Redis, service: _StoredSettings):
    import app.core.http as http_mod
    import app.core.redis as redis_mod
    import app.services.integration_settings.providers.zalo as zalo_provider_mod

    class _Response:
        @staticmethod
        def json():
            return {"access_token": "rotated-access", "refresh_token": "rotated-refresh"}

    class _Client:
        async def post(self, *_args, **_kwargs):
            return _Response()

    async def _client_factory(*_args, **_kwargs):
        return _Client()

    scheduled: list[dict] = []

    async def _audit(_db, **kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(redis_mod, "get_redis", lambda: redis)
    monkeypatch.setattr(http_mod, "get_http_client", _client_factory)
    monkeypatch.setattr(zalo_provider_mod, "record_audit", _audit)
    service.db = _CommitOnly()
    return scheduled


async def test_refresh_rotates_one_accounts_own_credentials(monkeypatch):
    service = _StoredSettings(
        {
            oa_account_setting_key(ZALO_OA_REFRESH_TOKEN, SECOND_OA_ID): "second-refresh",
            oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, SECOND_OA_ID): "second-stale",
            ZALO_OA_REFRESH_TOKEN: "original-refresh",
        }
    )
    redis = _Redis()
    audited = _refresh_harness(monkeypatch, redis, service)

    token = await service.refresh_oa_access_token(SECOND_OA_ID)

    assert token == "rotated-access"
    assert service.writes == [
        (oa_account_setting_key(ZALO_OA_ACCESS_TOKEN, SECOND_OA_ID), "rotated-access"),
        (oa_account_setting_key(ZALO_OA_REFRESH_TOKEN, SECOND_OA_ID), "rotated-refresh"),
    ]
    # One OA's single-use refresh token must not block another OA's refresh.
    assert redis.locks == [f"zalo:oa:token:refresh:{SECOND_OA_ID}"]
    assert audited[0]["payload"]["account_key"] == SECOND_OA_ID


async def test_refresh_keeps_the_singleton_keys_for_the_default_account(monkeypatch):
    service = _StoredSettings({ZALO_OA_REFRESH_TOKEN: "original-refresh"})
    redis = _Redis()
    _refresh_harness(monkeypatch, redis, service)

    token = await service.refresh_oa_access_token()

    assert token == "rotated-access"
    assert service.writes == [
        (ZALO_OA_ACCESS_TOKEN, "rotated-access"),
        (ZALO_OA_REFRESH_TOKEN, "rotated-refresh"),
    ]
    assert redis.locks == ["zalo:oa:token:refresh"]


async def test_refresh_needs_that_accounts_refresh_token(monkeypatch):
    service = _StoredSettings({ZALO_OA_REFRESH_TOKEN: "original-refresh"})
    redis = _Redis()
    _refresh_harness(monkeypatch, redis, service)

    # A second OA with no stored refresh token must not redeem the original's.
    assert await service.refresh_oa_access_token(SECOND_OA_ID) is None
    assert redis.locks == []


async def test_linking_the_original_oa_again_is_refused(monkeypatch):
    """Same access token ⇒ same OA ⇒ re-keying its history must not happen."""
    db = _ScalarSession([None])
    _use_fake_settings(monkeypatch, default_access_token="original-access")

    with pytest.raises(ZaloOaAccountInvalidError):
        await ZaloOaAccountLifecycle(db).link(  # type: ignore[arg-type]
            oa_id=SECOND_OA_ID,
            label="",
            credentials={ZALO_OA_ACCESS_TOKEN: "original-access"},
        )

    assert db.added == []
