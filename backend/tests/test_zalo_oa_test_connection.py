"""L3 verify endpoint (manual admin probe) + admin_view OA signature key is null.

Inbound OA webhook signature verification is retired (see app/api/webhooks.py);
the manual POST /zalo/oa/verify-signature probe remains as a diagnostic for a
future cutover when a dedicated Zalo webhook signing secret is available.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# L3: the verify-captured-event endpoint
# ---------------------------------------------------------------------------


class _IntSvc:
    config = None

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self, account_key=None):
        return self.config


@pytest.mark.asyncio
async def test_verify_endpoint_accepts_documented_digest(monkeypatch):
    from app.api import integrations
    from app.schemas.integrations import ZaloOaSignatureVerifyRequest
    from app.services.integration_settings import ZaloRuntimeConfig

    app_id, secret = "app-1", "secret"
    raw = json.dumps({"app_id": app_id, "timestamp": "1700000000"}, separators=(",", ":"))
    digest = hashlib.sha256((app_id + raw + "1700000000" + secret).encode("utf-8")).hexdigest()
    _IntSvc.config = ZaloRuntimeConfig(
        oa_app_id=app_id, oa_secret_key=secret, oa_access_token="t", oa_refresh_token="r"
    )
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _IntSvc)

    out = await integrations.verify_zalo_oa_signature(
        body=ZaloOaSignatureVerifyRequest(
            signature=f"mac={digest}", raw_body=raw, timestamp="1700000000"
        ),
        _admin=object(),
        db=object(),
    )
    assert out.verified is True
    assert out.secret_configured is True
    assert out.matched_label is not None


@pytest.mark.asyncio
async def test_verify_endpoint_rejects_wrong_secret(monkeypatch):
    from app.api import integrations
    from app.schemas.integrations import ZaloOaSignatureVerifyRequest
    from app.services.integration_settings import ZaloRuntimeConfig

    _IntSvc.config = ZaloRuntimeConfig(
        oa_app_id="app-1", oa_secret_key="secret", oa_access_token="t", oa_refresh_token="r"
    )
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _IntSvc)
    out = await integrations.verify_zalo_oa_signature(
        body=ZaloOaSignatureVerifyRequest(
            signature="mac=deadbeef", raw_body='{"app_id":"app-1"}', timestamp="1"
        ),
        _admin=object(),
        db=object(),
    )
    assert out.verified is False
    assert out.secret_configured is True


@pytest.mark.asyncio
async def test_verify_endpoint_reports_missing_secret(monkeypatch):
    from app.api import integrations
    from app.schemas.integrations import ZaloOaSignatureVerifyRequest
    from app.services.integration_settings import ZaloRuntimeConfig

    _IntSvc.config = ZaloRuntimeConfig()  # nothing configured
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _IntSvc)
    out = await integrations.verify_zalo_oa_signature(
        body=ZaloOaSignatureVerifyRequest(signature="mac=x", raw_body="{}", timestamp=""),
        _admin=object(),
        db=object(),
    )
    assert out.verified is False
    assert out.secret_configured is False


@pytest.mark.asyncio
async def test_verify_endpoint_reports_malformed_body(monkeypatch):
    from app.api import integrations
    from app.schemas.integrations import ZaloOaSignatureVerifyRequest
    from app.services.integration_settings import ZaloRuntimeConfig

    _IntSvc.config = ZaloRuntimeConfig(
        oa_app_id="app-1", oa_secret_key="secret", oa_access_token="t", oa_refresh_token="r"
    )
    monkeypatch.setattr(integrations, "IntegrationSettingsService", _IntSvc)
    out = await integrations.verify_zalo_oa_signature(
        body=ZaloOaSignatureVerifyRequest(signature="mac=x", raw_body="{not-json", timestamp=""),
        _admin=object(),
        db=object(),
    )
    assert out.verified is False
    assert "json" in out.detail.lower()


# ---------------------------------------------------------------------------
# admin_view: OA signature key is null (inbound verification retired)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_view_oa_signature_health_is_null(monkeypatch):
    from app.services.integration_settings import IntegrationSettingsService, ZaloRuntimeConfig

    iss = IntegrationSettingsService.__new__(IntegrationSettingsService)
    monkeypatch.setattr(iss, "resolve_zalo", AsyncMock(return_value=ZaloRuntimeConfig()))

    view = await iss.admin_view()
    assert view["zalo_oa_webhook_signature"] is None
