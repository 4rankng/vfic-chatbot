"""Wiring: webhook records signature health; L3 verify endpoint; admin_view surfaces health."""

from __future__ import annotations

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import pytest


class _FakeRequest:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


# ---------------------------------------------------------------------------
# L1: the inbound webhook records the signature outcome
# ---------------------------------------------------------------------------


class _WebhookSvc:
    """Stub for IntegrationSettingsService as used by app.api.webhooks."""

    config = None

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self):
        return self.config


@pytest.mark.asyncio
async def test_oa_webhook_records_verified_on_valid_signature(monkeypatch):
    from app.api import webhooks
    from app.services.integration_settings import ZaloRuntimeConfig

    app_id, secret = "app-1", "secret"
    payload = {
        "app_id": app_id,
        "timestamp": "1700000000",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(app_id.encode() + raw + b"1700000000" + secret.encode()).hexdigest()

    _WebhookSvc.config = ZaloRuntimeConfig(
        oa_app_id=app_id, oa_secret_key=secret, oa_access_token="t"
    )
    recorder = AsyncMock()
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", _WebhookSvc)
    monkeypatch.setattr(webhooks, "record_oa_signature", recorder)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        webhooks.ZaloWebhookService, "handle", AsyncMock(return_value={"status": "queued"})
    )

    req = _FakeRequest(
        raw,
        headers={"x-zevent-signature": f"mac={digest}", "x-zevent-timestamp": "1700000000"},
    )
    resp = await webhooks.zalo_oa_webhook(req, db=AsyncMock())
    await asyncio.sleep(0)  # let the fire-and-forget health record run

    assert resp.status_code == 200
    recorder.assert_called_once_with(ok=True)


@pytest.mark.asyncio
async def test_oa_webhook_uses_event_app_id_for_signature(monkeypatch):
    from app.api import webhooks
    from app.services.integration_settings import ZaloRuntimeConfig

    event_app_id, secret = "developer-app-1", "secret"
    payload = {
        "app_id": event_app_id,
        "timestamp": "1700000000",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(
        event_app_id.encode() + raw + b"1700000000" + secret.encode()
    ).hexdigest()

    # An administrator may have entered the OA ID in the legacy App ID field.
    # Authenticity still comes from the event App ID plus the configured secret.
    _WebhookSvc.config = ZaloRuntimeConfig(
        oa_app_id="oa-id-not-app-id", oa_secret_key=secret, oa_access_token="t"
    )
    recorder = AsyncMock()
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", _WebhookSvc)
    monkeypatch.setattr(webhooks, "record_oa_signature", recorder)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=object()))
    handler = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handler)

    req = _FakeRequest(raw, headers={"x-zevent-signature": f"mac={digest}"})
    resp = await webhooks.zalo_oa_webhook(req, db=AsyncMock())
    await asyncio.sleep(0)

    assert resp.status_code == 200
    recorder.assert_called_once_with(ok=True)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_oa_webhook_records_mismatch_but_still_processes(monkeypatch):
    """Signature verification is currently non-blocking: a mismatch is recorded to
    the health badge, but the event is still dispatched (otherwise a wrong/stale OA
    secret drops every real event, including user_seen_message receipts)."""
    from app.api import webhooks
    from app.services.integration_settings import ZaloRuntimeConfig

    _WebhookSvc.config = ZaloRuntimeConfig(
        oa_app_id="app-1", oa_secret_key="secret", oa_access_token="t"
    )
    recorder = AsyncMock()
    monkeypatch.setattr(webhooks, "IntegrationSettingsService", _WebhookSvc)
    monkeypatch.setattr(webhooks, "record_oa_signature", recorder)
    monkeypatch.setattr(webhooks, "_runtime_authority_or_inactive", AsyncMock(return_value=object()))
    handler = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(webhooks.ZaloWebhookService, "handle", handler)

    raw = json.dumps(
        {
            "app_id": "app-1",
            "event_name": "user_send_text",
            "sender": {"id": "u1"},
            "message": {"text": "hi", "msg_id": "m"},
        }
    ).encode("utf-8")
    req = _FakeRequest(
        raw, headers={"x-zevent-signature": "mac=deadbeef", "x-zevent-timestamp": "1"}
    )
    resp = await webhooks.zalo_oa_webhook(req, db=AsyncMock())
    await asyncio.sleep(0)  # let the fire-and-forget health record run

    assert resp.status_code == 200
    recorder.assert_called_once_with(ok=False)
    handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# L3: the verify-captured-event endpoint
# ---------------------------------------------------------------------------


class _IntSvc:
    config = None

    def __init__(self, _db) -> None:
        pass

    async def resolve_zalo(self):
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
# admin_view surfaces the passive signature health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_view_includes_oa_signature_health(monkeypatch):
    import app.services.zalo_oa_health as health_mod
    from app.services.integration_settings import IntegrationSettingsService, ZaloRuntimeConfig

    iss = IntegrationSettingsService.__new__(IntegrationSettingsService)
    monkeypatch.setattr(iss, "resolve_zalo", AsyncMock(return_value=ZaloRuntimeConfig()))
    monkeypatch.setattr(
        health_mod,
        "read_oa_signature_health",
        AsyncMock(return_value={"last_status": "mismatched", "consec_failures": 3}),
    )

    view = await iss.admin_view()
    assert view["zalo_oa_webhook_signature"]["last_status"] == "mismatched"
    assert view["zalo_oa_webhook_signature"]["consec_failures"] == 3
