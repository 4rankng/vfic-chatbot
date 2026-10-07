"""The TingTing support OA's read side: routing state and the admin view.

The link flow itself is gone — payroll owns the credentials (owner ruling
2026-10-07), so there is nothing left to paste, probe, or rotate. What the
tests pin is what routing and the reset gate still depend on: the verified
OA id read from the channel account's metadata, and an admin view that
exposes the payroll-owned token's age without ever exposing a credential.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.channels import types as ct
from app.models.channel_account import ChannelAccount
from app.services.tingting_oa import (
    TINGTING_OA_TOKEN_MANAGED_NOTE,
    TingtingOaLinkService,
)

_OA_ID = "3383849659955472174"


class _ScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Minimal AsyncSession: one channel account, optional token row."""

    def __init__(self, account: ChannelAccount | None, token_row=None) -> None:
        self._account = account
        self._token_row = token_row
        self.commits = 0

    async def scalars(self, _stmt) -> _ScalarResult:
        rows = [self._account] if self._account is not None else []
        return _ScalarResult(rows)

    async def scalar(self, _stmt):
        return self._account

    async def get(self, _model, key):
        return self._token_row if key == "zalo_oa_access_token:tingting" else None


def _linked_account(**metadata) -> ChannelAccount:
    return ChannelAccount(
        provider=ct.PROVIDER_ZALO_OA,
        account_key="tingting",
        label="Ting Ting Software Solution",
        status="ACTIVE",
        generation=1,
        provider_metadata={"oa_id": _OA_ID, "name": "Ting Ting Software Solution", **metadata},
    )


@pytest.mark.asyncio
async def test_verified_oa_id_is_what_routing_matches():
    """The webhook router's read: the metadata id, never a typed value."""
    db = _Session(_linked_account())
    service = TingtingOaLinkService(db)  # type: ignore[arg-type]

    assert await service.verified_oa_id() == _OA_ID
    assert await service.is_verified() is True


@pytest.mark.asyncio
async def test_an_inactive_or_missing_account_matches_nothing():
    db = _Session(None)
    service = TingtingOaLinkService(db)  # type: ignore[arg-type]
    assert await service.verified_oa_id() == ""

    inactive = _linked_account()
    inactive.status = "INACTIVE"
    db = _Session(inactive)
    service = TingtingOaLinkService(db)  # type: ignore[arg-type]
    assert await service.verified_oa_id() == ""


@pytest.mark.asyncio
async def test_view_reports_token_age_and_ownership_but_no_credential():
    updated = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    db = _Session(
        _linked_account(),
        token_row=SimpleNamespace(updated_at=updated),
    )
    service = TingtingOaLinkService(db)  # type: ignore[arg-type]

    view = await service.view()

    assert view["oa_linked"] is True
    assert view["oa_id"] == _OA_ID
    assert view["oa_token_updated_at"] == updated.isoformat()
    assert view["oa_token_managed_note"] == TINGTING_OA_TOKEN_MANAGED_NOTE
    # The payroll handover removed every credential field from the view.
    assert "oa_app_id" not in view
    assert "oa_secret_key" not in view
    assert "oa_access_token" not in view
    assert "oa_refresh_token" not in view


@pytest.mark.asyncio
async def test_view_without_a_token_row_reports_none():
    db = _Session(_linked_account())
    service = TingtingOaLinkService(db)  # type: ignore[arg-type]

    view = await service.view()

    assert view["oa_linked"] is True
    assert view["oa_token_updated_at"] is None
