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
    def __init__(self, *, set_ok: bool = True) -> None:
        self._set_ok = set_ok
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        return self._set_ok

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


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

    monkeypatch.setattr("app.services.integration_settings.record_audit", fake_record_audit)

    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new", "refresh_token": "rt-2"})
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    fake_redis = _FakeRedis(set_ok=True)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)

    token = await service.refresh_oa_access_token()

    assert token == "at-new"
    assert fake_client.last_headers == {"secret_key": "oa-secret"}
    assert db.committed is True
    assert service.cipher.decrypt(db._by_key[ZALO_OA_ACCESS_TOKEN].encrypted_value) == "at-new"
    assert service.cipher.decrypt(db._by_key[ZALO_OA_REFRESH_TOKEN].encrypted_value) == "rt-2"
    assert fake_redis.deleted == ["zalo:oa:token:refresh"]
    assert audits and audits[0]["action"] == "refresh_zalo_oa_token"


@pytest.mark.asyncio
async def test_refresh_returns_stored_token_when_lock_held(monkeypatch):
    monkeypatch.setattr(
        "app.services.integration_settings.record_audit",
        AsyncMockNoop(),
    )
    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"access_token": "at-new"})
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
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
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)

    token = await service.refresh_oa_access_token()

    assert token is None
    assert fake_client.posted == 0


@pytest.mark.asyncio
async def test_refresh_returns_none_on_zalo_error(monkeypatch):
    service = IntegrationSettingsService(_RefreshDb([]), settings=_Settings())
    db = _RefreshDb(_seed(service))
    service = IntegrationSettingsService(db, settings=_Settings())

    fake_client = _FakeClient({"error": -1, "message": "invalid refresh_token"})
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis(set_ok=True))

    token = await service.refresh_oa_access_token()

    assert token is None
    assert db.committed is False


class AsyncMockNoop:
    async def __call__(self, *_args, **_kwargs):
        return None
