"""OA access-token refresh: Redis lock, persistence, failure modes.

All I/O (httpx, Redis, DB) is mocked — no live process required.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.integration_settings import (
    IntegrationSettingsService,
    ZALO_OA_ACCESS_TOKEN,
    ZALO_OA_APP_ID,
    ZALO_OA_REFRESH_LOCK_KEY,
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
    zalo_oa_refresh_token = ""
    zalo_bot_request_timeout = 5


class _Row:
    def __init__(self, key: str, encrypted_value: str) -> None:
        self.key = key
        self.encrypted_value = encrypted_value
        self.is_secret = True
        self.updated_by = None


class _ScalarResult:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _RefreshDb:
    """Fake AsyncSession supporting resolve_zalo (scalars) + _write_secret (get/add/commit)."""

    def __init__(self, rows: list[_Row]) -> None:
        self._by_key = {r.key: r for r in rows}
        self.added: list[_Row] = []
        self.committed = False

    async def scalars(self, _query: Any) -> _ScalarResult:
        return _ScalarResult(list(self._by_key.values()))

    async def get(self, _model: Any, key: str) -> _Row | None:
        return self._by_key.get(key)

    def add(self, row: _Row) -> None:
        self._by_key[row.key] = row
        self.added.append(row)

    async def commit(self) -> None:
        self.committed = True


class _FakeRedis:
    """Value-aware Redis double: records SET args and models the release CAS."""

    def __init__(self, *, set_ok: bool = True) -> None:
        self._set_ok = set_ok
        self._store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None, bool]] = []
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        self.set_calls.append((key, value, ex, nx))
        if not self._set_ok or (nx and key in self._store):
            return False
        self._store[key] = value
        return "OK"

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1 if self._store.pop(key, None) is not None else 0

    async def eval(self, _script: str, _numkeys: int, *args: str) -> int:
        """The only script in play: delete iff the stored value is ours."""
        key, owner = args[0], args[1]
        if self._store.get(key) != owner:
            return 0
        self.deleted.append(key)
        self._store.pop(key, None)
        return 1


class _FakeResp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.posted = 0

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def post(self, url: str, *, json=None, headers=None, **kw):
        self.posted += 1
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return _FakeResp(self._data)


def _seed(service: IntegrationSettingsService) -> list[_Row]:
    c = service.cipher
    return [
        _Row(ZALO_OA_APP_ID, c.encrypt("app-1")),
        _Row(ZALO_OA_SECRET_KEY, c.encrypt("oa-secret")),
        _Row(ZALO_OA_REFRESH_TOKEN, c.encrypt("rt-1")),
        _Row(ZALO_OA_ACCESS_TOKEN, c.encrypt("at-old")),
    ]


@pytest.mark.asyncio
async def test_refresh_persists_new_token_and_rotates_refresh_token(monkeypatch):
    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr("app.services.integration_settings.providers.zalo.record_audit", fake_record_audit)

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new", "refresh_token": "rt-2"})
    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)
    fake_redis = _FakeRedis(set_ok=True)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    token = await service.refresh_oa_access_token()

    assert token == "at-new"
    assert fake_client.last_headers == {"secret_key": "oa-secret"}
    assert db.committed is True
    assert service.cipher.decrypt(db._by_key[ZALO_OA_ACCESS_TOKEN].encrypted_value) == "at-new"
    assert service.cipher.decrypt(db._by_key[ZALO_OA_REFRESH_TOKEN].encrypted_value) == "rt-2"
    assert fake_redis.deleted == [ZALO_OA_REFRESH_LOCK_KEY]
    assert audits and audits[0]["action"] == "refresh_zalo_oa_token"


@pytest.mark.asyncio
async def test_refresh_lock_ttl_exceeds_the_guarded_timeout_budget(monkeypatch):
    """REL-03: the TTL must outlive the work it guards.

    The guarded work is the caller's failed send plus the refresh POST (each
    bounded by ``zalo_bot_request_timeout``) and the persist+commit. A shorter
    TTL expires mid-flight, letting a second worker redeem the same single-use
    refresh token.
    """
    monkeypatch.setattr("app.services.integration_settings.providers.zalo.record_audit", AsyncMockNoop())

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", _FakeClient({"access_token": "at-new"}))
    fake_redis = _FakeRedis(set_ok=True)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    await service.refresh_oa_access_token()

    key, owner, ttl, nx = fake_redis.set_calls[0]
    assert key == ZALO_OA_REFRESH_LOCK_KEY
    assert nx is True
    # A per-holder UUID, not a shared constant: the release CAS depends on it.
    assert owner != "1" and len(owner) == 32
    assert ttl is not None and ttl > 2 * _Settings.zalo_bot_request_timeout


@pytest.mark.asyncio
async def test_refresh_release_never_deletes_a_lock_owned_by_another_worker(monkeypatch):
    """REL-03: a straggler must not release a successor's lock.

    Simulates the TTL expiring mid-refresh and a second worker taking the lock
    before the first releases: the blind DELETE this replaced would have removed
    the successor's marker and admitted a third redeemer of the single-use
    refresh token.
    """
    monkeypatch.setattr("app.services.integration_settings.providers.zalo.record_audit", AsyncMockNoop())

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_redis = _FakeRedis(set_ok=True)
    fake_client = _FakeClient({"access_token": "at-new", "refresh_token": "rt-2"})

    original_post = fake_client.post

    async def post_then_hand_over_lock(*args, **kwargs):
        response = await original_post(*args, **kwargs)
        # The holder outlived its TTL; a successor now owns the marker.
        fake_redis._store[ZALO_OA_REFRESH_LOCK_KEY] = "successor-owner"
        return response

    fake_client.post = post_then_hand_over_lock

    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    token = await service.refresh_oa_access_token()

    assert token == "at-new"
    assert fake_redis.deleted == []
    assert fake_redis._store[ZALO_OA_REFRESH_LOCK_KEY] == "successor-owner"


@pytest.mark.asyncio
async def test_refresh_returns_stored_token_when_lock_held(monkeypatch):
    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.record_audit",
        AsyncMockNoop(),
    )
    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new"})
    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=False))
    monkeypatch.setattr("asyncio.sleep", AsyncMockNoop())

    token = await service.refresh_oa_access_token()

    # Another worker holds the lock and no new token appears: never retry with
    # the known-expired access token.
    assert token is None
    assert fake_client.posted == 0
    assert db.committed is False


@pytest.mark.asyncio
async def test_refresh_returns_none_when_refresh_token_missing(monkeypatch):
    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    cipher = service.cipher
    db = _RefreshDb(
        [
            _Row(ZALO_OA_APP_ID, cipher.encrypt("app-1")),
            _Row(ZALO_OA_ACCESS_TOKEN, cipher.encrypt("at-old")),
        ]
    )
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new"})
    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)

    token = await service.refresh_oa_access_token()

    assert token is None
    assert fake_client.posted == 0


@pytest.mark.asyncio
async def test_refresh_returns_none_on_zalo_error(monkeypatch):
    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"error": -1, "message": "invalid refresh_token"})
    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=True))

    token = await service.refresh_oa_access_token()

    assert token is None
    assert db.committed is False


class AsyncMockNoop:
    async def __call__(self, *_args, **_kwargs):
        return None


# ── The TingTing account never touches Zalo OAuth: payroll owns its pair ────


def _tingting_seed(service: IntegrationSettingsService) -> list[_Row]:
    """The account's stored rows: a fossil refresh token, an old access token."""
    c = service.cipher
    return [
        _Row(f"{ZALO_OA_REFRESH_TOKEN}:tingting", c.encrypt("dead-rt")),
        _Row(f"{ZALO_OA_ACCESS_TOKEN}:tingting", c.encrypt("at-old")),
    ]


@pytest.mark.asyncio
async def test_tingting_refresh_pulls_from_payroll_and_stores(monkeypatch):
    from unittest.mock import AsyncMock

    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.record_audit", fake_record_audit
    )
    fetch = AsyncMock(return_value="at-payroll-1")
    monkeypatch.setattr(
        "app.services.tingting_api.TingtingApiService.fetch_zalo_oa_access_token", fetch
    )
    # No lock may be taken: a pull is idempotent, the single-use refresh token
    # it would otherwise serialize does not exist for this account.
    fake_redis = _FakeRedis(set_ok=True)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_tingting_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    token = await service.refresh_oa_access_token("tingting")

    assert token == "at-payroll-1"
    fetch.assert_awaited_once_with()
    assert fake_redis.set_calls == []
    assert db.committed is True
    assert (
        service.cipher.decrypt(db._by_key[f"{ZALO_OA_ACCESS_TOKEN}:tingting"].encrypted_value)
        == "at-payroll-1"
    )
    # Same audit action as the Zalo branch, marked with its source.
    assert audits and audits[0]["action"] == "refresh_zalo_oa_token"
    assert audits[0]["payload"] == {"account_key": "tingting", "source": "payroll"}


@pytest.mark.asyncio
async def test_tingting_refresh_payroll_failure_keeps_the_none_contract(monkeypatch):
    from unittest.mock import AsyncMock

    alerts: list[dict] = []

    async def fake_notify(*_args, **kwargs):
        alerts.append(kwargs)

    monkeypatch.setattr("app.services.push.notify_admins", fake_notify)
    monkeypatch.setattr(
        "app.services.tingting_api.TingtingApiService.fetch_zalo_oa_access_token",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=True))

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_tingting_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    token = await service.refresh_oa_access_token("tingting")

    # The send-path failure contract: None, no write, one deduped admin alert.
    assert token is None
    assert db.committed is False
    assert db.added == []
    assert alerts and alerts[0]["dedupe_key"] == "zalo-oa-refresh:tingting"


@pytest.mark.asyncio
async def test_non_tingting_account_still_refreshes_through_zalo_oauth(monkeypatch):
    """The payroll branch keys on the tingting account only — the default OA
    (and any other account) keeps redeeming its own refresh token."""
    from unittest.mock import AsyncMock

    fetch = AsyncMock(return_value="at-from-payroll")
    monkeypatch.setattr(
        "app.services.tingting_api.TingtingApiService.fetch_zalo_oa_access_token", fetch
    )
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=True))

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new", "refresh_token": "rt-2"})
    from tests.helpers.http_fake import register_fake_client as _reg_fake

    _reg_fake("zalo_oa_token", fake_client)

    token = await service.refresh_oa_access_token("default:zalo_oa")

    assert token == "at-new"
    assert fake_client.posted == 1
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pushed_token_store_writes_commits_and_audits(monkeypatch):
    """The push webhook's write path: same storage as the pull, one commit."""
    from app.services.integration_settings import ZALO_OA_ACCESS_TOKEN

    audits: list[dict] = []

    async def fake_record_audit(*_args, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(
        "app.services.integration_settings.providers.zalo.record_audit", fake_record_audit
    )
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=True))

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb([])
    service = IntegrationSettingsService(db, settings=_Settings())

    stored = await service.store_pushed_oa_token("tingting", "at-pushed-1")

    assert stored == [f"{ZALO_OA_ACCESS_TOKEN}:tingting"]
    assert db.committed is True
    assert (
        service.cipher.decrypt(db._by_key[f"{ZALO_OA_ACCESS_TOKEN}:tingting"].encrypted_value)
        == "at-pushed-1"
    )
    assert audits[0]["action"] == "store_pushed_zalo_oa_token"
    assert audits[0]["payload"] == {"account_key": "tingting", "source": "payroll"}
