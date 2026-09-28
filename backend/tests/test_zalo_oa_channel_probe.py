"""The Zalo OA channel diagnostic must never redeem a credential.

A Zalo refresh token is single-use. The probe used to POST a second grant to
``oauth.zaloapp.com`` purely to tell the admin whether the secret key was valid
— discarding the pair Zalo issued in the process and leaving the stored token
dead, which is the "silent refresh" behind OPS-31. It now reports the actionable
conclusion instead, and the only redemption left belongs to the provider, which
persists whatever it is issued.
"""

from __future__ import annotations

import inspect

from app.services.integrations import zalo_diagnostics
from app.services.integrations.zalo_diagnostics import probe_zalo_oa_channel
from app.services.zalo_bot_service import SendResult

TOKEN_URL_HOST = "oauth.zaloapp.com"


class _Cfg:
    oa_app_id = "app-1"
    oa_secret_key = "secret-1"
    oa_access_token = "access-1"
    oa_refresh_token = "refresh-1"


class _Service:
    """Records every grant the probe attempts; returns nothing, as Zalo did."""

    settings = object()

    def __init__(self, _db) -> None:
        self.refresh_calls = 0

    async def resolve_zalo(self, account_key=None):
        return _Cfg()

    async def refresh_oa_access_token(self, account_key=None):
        self.refresh_calls += 1
        return None


def _patch(monkeypatch, *, probe):
    import types
    from unittest.mock import AsyncMock

    service = _Service(None)
    monkeypatch.setattr(
        zalo_diagnostics, "IntegrationSettingsService", lambda _db: service
    )
    monkeypatch.setattr(
        zalo_diagnostics,
        "ZaloOASender",
        lambda **_kw: types.SimpleNamespace(get_oa_info=AsyncMock(return_value=probe)),
    )
    return service


async def test_a_rejected_refresh_reports_the_fix_instead_of_redeeming_again(monkeypatch):
    service = _patch(
        monkeypatch,
        probe=SendResult(ok=False, error="access token access-1 has expired"),
    )

    result = await probe_zalo_oa_channel(None)  # type: ignore[arg-type]

    # Exactly one grant attempt, and it belongs to the provider (which persists
    # what it is issued) — not to the probe.
    assert service.refresh_calls == 1
    assert result.oa_token_expired is True
    assert result.oa_refresh_ok is False
    # The secret key can no longer be singled out without burning a token, so
    # the probe says "not determined" instead of guessing.
    assert result.oa_secret_valid is None
    assert any("-14014" in message for message in result.errors)
    # Nothing about the credentials is echoed back.
    for secret in ("access-1", "refresh-1", "secret-1"):
        assert all(secret not in message for message in result.errors)


def test_the_probe_module_holds_no_token_endpoint_of_its_own():
    """Structural guard against re-introducing a raw grant here.

    Any call to the token endpoint from this module redeems a single-use
    credential, so it must stay delegated to the provider.
    """
    assert TOKEN_URL_HOST not in inspect.getsource(zalo_diagnostics)
