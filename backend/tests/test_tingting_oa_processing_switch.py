"""The TingTing OA processing kill switch: helper defaults + settings round-trip.

The switch (``tingting_oa_enabled``) is a non-secret integration setting in the
TingTing group. Absent row means enabled, so an install that never touched it
keeps processing; a read failure fails open; an explicit "false" stands turns
on that OA down in the worker (covered in ``test_chat_turn_tingting_gate.py``).
"""

from __future__ import annotations

import pytest

from app.models.integration import IntegrationSetting
from app.services.integration_settings import IntegrationSettingsService
from app.services.integration_settings.providers.tingting import TINGTING_OA_ENABLED
from app.services.tingting_oa import processing_enabled

SWITCH_KEY = TINGTING_OA_ENABLED


class _Settings:
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    # admin_tingting_view resolves the Zalo runtime config, which falls back
    # to these env mirrors when nothing is stored.
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
    zalo_oa_refresh_token = ""


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    """Minimal session: integration rows in a dict, every other read empty."""

    def __init__(self, rows=()) -> None:
        self.rows = {row.key: row for row in rows}
        self.added: list[object] = []
        self.commits = 0

    async def scalars(self, _query):
        return _Result(list(self.rows.values()))

    async def scalar(self, _query):
        return None

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, obj) -> None:
        self.added.append(obj)
        key = getattr(obj, "key", None)
        if key:
            self.rows[key] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class _ExplodingDb(_Db):
    """A settings store outage: every read raises."""

    async def scalars(self, _query):
        raise RuntimeError("settings store unavailable")


def _row(value: str) -> IntegrationSetting:
    return IntegrationSetting(key=SWITCH_KEY, encrypted_value=value, is_secret=False)


@pytest.mark.asyncio
async def test_processing_enabled_defaults_on_when_setting_absent():
    db = _Db()

    assert await processing_enabled(db) is True


@pytest.mark.asyncio
async def test_processing_enabled_reads_explicit_false():
    db = _Db([_row("false")])

    assert await processing_enabled(db) is False


@pytest.mark.asyncio
async def test_processing_enabled_reads_explicit_true():
    db = _Db([_row("true")])

    assert await processing_enabled(db) is True


@pytest.mark.asyncio
async def test_processing_enabled_fails_open_on_read_error(caplog):
    db = _ExplodingDb()

    assert await processing_enabled(db) is True
    assert any("tingting oa enabled read failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_update_tingting_persists_switch_off_plaintext_and_audits():
    db = _Db()
    service = IntegrationSettingsService(db, settings=_Settings())

    view = await service.update_tingting({"tingting_oa_enabled": False}, actor_id=None)

    assert view["tingting_oa_enabled"] is False
    stored = db.rows[SWITCH_KEY]
    assert stored.encrypted_value == "false", "a non-secret switch stores plaintext"
    assert stored.is_secret is False
    assert db.commits == 1
    audits = [obj for obj in db.added if getattr(obj, "action", "") == "update_tingting_integration_settings"]
    assert audits and audits[-1].payload == {"tingting_oa_enabled": False}


@pytest.mark.asyncio
async def test_update_tingting_switch_round_trips_off_then_on():
    db = _Db()
    service = IntegrationSettingsService(db, settings=_Settings())

    await service.update_tingting({"tingting_oa_enabled": False}, actor_id=None)
    assert await service.resolve_tingting_oa_enabled() is False

    await service.update_tingting({"tingting_oa_enabled": True}, actor_id=None)
    assert await service.resolve_tingting_oa_enabled() is True


@pytest.mark.asyncio
async def test_update_tingting_without_the_switch_keeps_stored_value():
    db = _Db([_row("false")])
    service = IntegrationSettingsService(db, settings=_Settings())
    commits_before = db.commits

    await service.update_tingting({}, actor_id=None)

    assert await service.resolve_tingting_oa_enabled() is False
    assert db.commits == commits_before, "no switch write, no switch commit"
