"""The TingTing support OA link: probe, register, expose, unlink.

The admin never types an OA id — Zalo's `getoa` is what names the OA, so the
probe is the link. These tests pin what happens on a good probe, a rejected one,
and a malformed id, plus the unlink that turns the reset flow off.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock

import pytest

from app.channels import types as ct
from app.models.channel_account import ChannelAccount
from app.services.tingting_oa import (
    TINGTING_OA_ACCOUNT_KEY,
    TingtingOaLinkError,
    TingtingOaLinkService,
)
from app.services.zalo_bot_service import SendResult


class _Session:
    """Session double: one canned ``scalar`` row, recorded writes."""

    def __init__(self, row: object | None = None) -> None:
        self._row = row
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, _stmt):
        # Reflect what this session has written, like a flush would.
        return self.added[-1] if self.added else self._row

    async def execute(self, _stmt):
        return types.SimpleNamespace(rowcount=1)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        return None


class _Settings:
    """Settings double holding one account's credentials and the pin."""

    stored: dict[str, str] = {}
    writes: list[tuple[str, dict]] = []
    pin: str = ""

    def __init__(self, _db, **_kwargs) -> None:
        pass

    async def oa_account_credentials_view(self, _account_key):
        return {
            "account_key": TINGTING_OA_ACCOUNT_KEY,
            "app_id": self.stored.get("zalo_oa_app_id", ""),
            "app_id_configured": bool(self.stored.get("zalo_oa_app_id")),
            "secret_key": {"configured": bool(self.stored.get("zalo_oa_secret_key"))},
            "access_token": {"configured": bool(self.stored.get("zalo_oa_access_token"))},
            "refresh_token": {"configured": bool(self.stored.get("zalo_oa_refresh_token"))},
        }

    async def resolve_zalo(self, _account_key=None):
        from app.services.integration_settings import ZaloRuntimeConfig

        return ZaloRuntimeConfig(
            oa_app_id=self.stored.get("zalo_oa_app_id", ""),
            oa_secret_key=self.stored.get("zalo_oa_secret_key", ""),
            oa_access_token=self.stored.get("zalo_oa_access_token", ""),
            oa_refresh_token=self.stored.get("zalo_oa_refresh_token", ""),
        )

    async def write_oa_account_credentials(self, account_key, values, *, actor_id=None):
        _Settings.writes.append((account_key, dict(values)))
        self.stored.update({k: v for k, v in values.items() if v})
        return sorted(values)

    async def clear_oa_account_credentials(self, _account_key):
        cleared = len([v for v in self.stored.values() if v])
        _Settings.stored = {}
        return cleared

    async def update_tingting(self, values, *, actor_id=None):
        _Settings.pin = str(values.get("reset_oa_id") or "")
        return {}


def _patch(monkeypatch, *, probe):
    import app.services.tingting_oa as mod

    monkeypatch.setattr(mod, "TingtingOaLinkService", TingtingOaLinkService)
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService", _Settings
    )
    monkeypatch.setattr(mod, "record_audit", AsyncMock())
    sender = types.SimpleNamespace(get_oa_info=AsyncMock(return_value=probe))
    monkeypatch.setattr("app.services.zalo_oa_service.ZaloOASender", lambda **_kw: sender)
    _Settings.stored = {}
    _Settings.writes = []
    _Settings.pin = ""
    return sender


def _ok(oa_id: str = "3383849659955472174", name: str = "Ting Ting Software Solution"):
    return SendResult(ok=True, raw={"error": 0, "data": {"oa_id": oa_id, "name": name}})


async def test_a_good_probe_registers_the_account_and_binds_the_flow(monkeypatch):
    _patch(monkeypatch, probe=_ok())
    db = _Session(None)

    view = await TingtingOaLinkService(db, settings=object()).link(  # type: ignore[arg-type]
        {
            "zalo_oa_app_id": "app-1",
            "zalo_oa_access_token": "access-1",
            "zalo_oa_refresh_token": "refresh-1",
        },
        actor_id=None,
    )

    assert view["oa_linked"] is True
    assert view["oa_id"] == "3383849659955472174"
    assert view["oa_name"] == "Ting Ting Software Solution"
    assert _Settings.pin == TINGTING_OA_ACCOUNT_KEY
    assert _Settings.writes == [
        (
            TINGTING_OA_ACCOUNT_KEY,
            {
                "zalo_oa_app_id": "app-1",
                "zalo_oa_access_token": "access-1",
                "zalo_oa_refresh_token": "refresh-1",
            },
        )
    ]
    account = db.added[0]
    assert isinstance(account, ChannelAccount)
    assert account.provider == ct.PROVIDER_ZALO_OA
    assert account.account_key == TINGTING_OA_ACCOUNT_KEY
    assert account.label == "Ting Ting Software Solution"
    assert account.provider_metadata["oa_id"] == "3383849659955472174"
    assert db.commits == 1


async def test_a_rejected_probe_stores_nothing_binding_and_reports_why(monkeypatch):
    _patch(
        monkeypatch,
        probe=SendResult(ok=False, error="access token access-1 is invalid"),
    )
    db = _Session(None)

    view = await TingtingOaLinkService(db, settings=object()).link(  # type: ignore[arg-type]
        {"zalo_oa_access_token": "access-1"},
        actor_id=None,
    )

    # Stored so the admin can fix one field and retry, but not linked and no pin:
    # the flow stays off until Zalo confirms the credentials.
    assert _Settings.writes[0][1] == {"zalo_oa_access_token": "access-1"}
    assert view["oa_linked"] is False
    assert view["oa_id"] == ""
    assert _Settings.pin == ""
    # The provider echoed the token back; it must not reach the admin view.
    assert "access-1" not in view["oa_last_error"]
    assert "[redacted]" in view["oa_last_error"]
    # The attempt itself is recorded (inactive, so it can neither route nor send).
    assert [a.status for a in db.added] == ["INACTIVE"]


async def test_a_malformed_oa_id_is_a_failed_probe(monkeypatch):
    _patch(monkeypatch, probe=_ok(oa_id="not-a-number"))

    view = await TingtingOaLinkService(_Session(None), settings=object()).link(  # type: ignore[arg-type]
        {"zalo_oa_access_token": "access-1"},
        actor_id=None,
    )

    assert view["oa_linked"] is False
    assert view["oa_last_error"] == "Zalo trả về mã OA không hợp lệ"


async def test_an_empty_access_token_is_refused(monkeypatch):
    _patch(monkeypatch, probe=_ok())

    with pytest.raises(TingtingOaLinkError):
        await TingtingOaLinkService(_Session(None), settings=object()).link(  # type: ignore[arg-type]
            {"zalo_oa_secret_key": "secret-1"},
            actor_id=None,
        )


async def test_unlink_drops_the_credentials_and_the_binding(monkeypatch):
    _patch(monkeypatch, probe=_ok())
    account = ChannelAccount(
        provider=ct.PROVIDER_ZALO_OA,
        account_key=TINGTING_OA_ACCOUNT_KEY,
        label="Ting Ting Software Solution",
        status="ACTIVE",
        generation=1,
        provider_metadata={"oa_id": "3383849659955472174"},
    )
    db = _Session(account)
    service = TingtingOaLinkService(db, settings=object())  # type: ignore[arg-type]

    view = await service.unlink(actor_id=None)

    assert account.status == "INACTIVE"
    assert account.generation == 2
    assert "oa_id" not in account.provider_metadata
    assert view["oa_linked"] is False
    assert _Settings.pin == ""


async def test_the_registered_id_is_what_routing_matches(monkeypatch):
    _patch(monkeypatch, probe=_ok(oa_id="555"))
    db = _Session(None)
    await TingtingOaLinkService(db, settings=object()).link(  # type: ignore[arg-type]
        {"zalo_oa_access_token": "access-1"}, actor_id=None
    )
    account = db.added[0]

    # Same read the webhook router uses: the metadata, not a typed value.
    assert account.provider_metadata["oa_id"] == "555"
