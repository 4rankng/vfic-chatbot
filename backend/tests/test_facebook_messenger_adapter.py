"""Tests for the Phase 5 Messenger signature verifier, normalizer, adapter, and policy.

Covers:
- Signature: valid/invalid/missing/malformed; constant-time verify token.
- Normalizer: text, echo, postback, attachment-only, empty text, missing mid,
  multi-entry batch, missing identity, delivery/read are not inbound.
- Adapter: account-key mismatch suppression, auth-revoked classification,
  send-text success; receipt parse (delivery + read).
- Policy: window open / expired / no inbound.
- Webhook edge: signature rejected before any business write; inactive Page
  ack; page-mismatch event dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels import types as ct
from app.channels.providers.facebook_messenger import (
    FacebookMessengerAdapter,
    FacebookMessengerNormalizer,
)
from app.channels.providers.facebook_policy import (
    MESSENGER_STANDARD_WINDOW,
    evaluate_send_eligibility,
)
from app.channels.providers.facebook_signature import (
    constant_time_verify_token,
    verify_messenger_signature,
)


# ─── signature ──────────────────────────────────────────────────────────────


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_valid():
    body = b'{"entry":[{"messaging":[]}]}'
    assert verify_messenger_signature(
        signature_header=_sign(body, "s3cr3t"), raw_body=body, app_secret="s3cr3t"
    ).verified


def test_signature_tampered_body_rejected():
    body = b'{"entry":[]}'
    assert not verify_messenger_signature(
        signature_header=_sign(body, "s3cr3t"), raw_body=b'{"entry":[{"x":1}]}', app_secret="s3cr3t"
    ).verified


def test_signature_missing_header_rejected():
    assert not verify_messenger_signature(
        signature_header="", raw_body=b"{}", app_secret="s3cr3t"
    ).verified


def test_signature_missing_secret_rejected():
    assert not verify_messenger_signature(
        signature_header="sha256=abc", raw_body=b"{}", app_secret=""
    ).verified


def test_signature_malformed_hex_rejected():
    assert not verify_messenger_signature(
        signature_header="sha256=not-hex!", raw_body=b"{}", app_secret="s3cr3t"
    ).verified


def test_verify_token_constant_time():
    assert constant_time_verify_token(sent="my-verify-token", expected="my-verify-token")
    assert not constant_time_verify_token(sent="wrong", expected="my-verify-token")
    assert not constant_time_verify_token(sent="anything", expected="")


# ─── normalizer ─────────────────────────────────────────────────────────────


def _msg_event(page_id="PAGE-1", psid="PSID-1", **msg_fields):
    return {
        "sender": {"id": psid},
        "recipient": {"id": page_id},
        "timestamp": 1700000000000,
        "message": msg_fields,
    }


def test_normalizer_extracts_text():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [_msg_event(mid="m.1", text="Xin chào")]}]}
    )
    assert len(msgs) == 1
    m = msgs[0]
    assert m.text == "Xin chào"
    assert m.external_message_id == "m.1"
    assert m.identity.provider == ct.PROVIDER_FACEBOOK_MESSENGER
    assert m.identity.account_key == "PAGE-1"
    assert m.identity.external_id == "PSID-1"
    assert ignored == {}


def test_normalizer_ignores_echo():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [_msg_event(mid="m.2", text="echo", is_echo=True)]}]}
    )
    assert msgs == []
    assert ignored.get("echo") == 1


def test_normalizer_ignores_postback():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "PSID-1"},
                            "recipient": {"id": "PAGE-1"},
                            "postback": {"title": "Get Started", "payload": "START"},
                        }
                    ]
                }
            ]
        }
    )
    assert msgs == []
    assert ignored.get("postback") == 1


def test_normalizer_ignores_attachment_only():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [_msg_event(mid="m.3", attachments=[{"type": "image"}])]}]}
    )
    assert msgs == []
    assert ignored.get("non_text") == 1


def test_normalizer_ignores_empty_text():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [_msg_event(mid="m.4", text="   ")]}]}
    )
    assert msgs == []
    assert ignored.get("empty_text") == 1


def test_normalizer_ignores_missing_mid():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [_msg_event(text="hi")]}]}  # no mid
    )
    assert msgs == []
    assert ignored.get("missing_mid") == 1


def test_normalizer_ignores_missing_identity():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {"entry": [{"messaging": [{"message": {"mid": "m.5", "text": "hi"}}]}]}
    )
    assert msgs == []
    assert ignored.get("missing_identity") == 1


def test_normalizer_delivery_is_not_inbound():
    norm = FacebookMessengerNormalizer()
    msgs, ignored = norm.normalize(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "PSID-1"},
                            "recipient": {"id": "PAGE-1"},
                            "delivery": {"mids": ["m.9"], "watermark": 1},
                        }
                    ]
                }
            ]
        }
    )
    assert msgs == []
    assert ignored.get("receipt_event") == 1


def test_normalizer_multi_entry_batch():
    """One POST may carry multiple entries/messaging items; each is normalized
    independently to its own durable outcome."""
    norm = FacebookMessengerNormalizer()
    payload = {
        "entry": [
            {"messaging": [_msg_event(mid="m.1", text="a")]},
            {
                "messaging": [
                    _msg_event(page_id="PAGE-1", psid="PSID-2", mid="m.2", text="b"),
                    _msg_event(mid="m.3", text="echo", is_echo=True),
                ]
            },
        ]
    }
    msgs, ignored = norm.normalize(payload)
    assert len(msgs) == 2
    assert {m.external_message_id for m in msgs} == {"m.1", "m.2"}
    assert ignored.get("echo") == 1


# ─── adapter ────────────────────────────────────────────────────────────────


def _adapter(page_id="PAGE-1"):
    cfg = MagicMock()
    cfg.page_id = page_id
    cfg.page_access_token = "EAAB-token"
    cfg.graph_api_version = "v25.0"
    cfg.graph_api_base = "https://graph.facebook.com"
    return FacebookMessengerAdapter(cfg)


def _cmd(account_key="PAGE-1", recipient_id="PSID-1"):
    return ct.OutboundTextCommand(
        provider=ct.PROVIDER_FACEBOOK_MESSENGER,
        account_key=account_key,
        recipient_id=recipient_id,
        text="reply",
        channel_account_generation=1,
    )


async def test_adapter_account_key_mismatch_suppressed():
    """A stale command for a different Page is suppressed (not sent)."""
    adapter = _adapter(page_id="PAGE-1")
    result = await adapter.send_text(_cmd(account_key="PAGE-OTHER"))
    assert not result.ok
    assert result.suppressed


async def test_adapter_send_success(monkeypatch):
    adapter = _adapter()
    monkeypatch.setattr(
        "app.channels.providers.facebook_messenger.graph_send_message",
        AsyncMock(return_value={"message_id": "m.100", "recipient_id": "PSID-1"}),
    )
    result = await adapter.send_text(_cmd())
    assert result.ok
    assert result.provider_message_id == "m.100"


async def test_adapter_auth_revoked_classification(monkeypatch):
    from app.channels.providers.facebook_oauth import FacebookOAuthError

    adapter = _adapter()
    # Meta code 190 = invalid/expired/revoked access token. The adapter branches
    # on the structured code, not brittle substring matching on the message.
    monkeypatch.setattr(
        "app.channels.providers.facebook_messenger.graph_send_message",
        AsyncMock(side_effect=FacebookOAuthError("session invalidated", code=190)),
    )
    result = await adapter.send_text(_cmd())
    assert not result.ok
    assert result.error_class == "auth_revoked"


async def test_adapter_auth_revoked_not_triggered_by_message_text(monkeypatch):
    """A message containing 'token' + 'expired' but code != 190 must NOT
    classify as auth_revoked — the structured code is the authority, not the
    (localized, varying) message text."""
    from app.channels.providers.facebook_oauth import FacebookOAuthError

    adapter = _adapter()
    monkeypatch.setattr(
        "app.channels.providers.facebook_messenger.graph_send_message",
        AsyncMock(side_effect=FacebookOAuthError("The token expired", code=10)),
    )
    result = await adapter.send_text(_cmd())
    assert result.error_class == "provider_error"


async def test_adapter_generic_provider_error(monkeypatch):
    from app.channels.providers.facebook_oauth import FacebookOAuthError

    adapter = _adapter()
    monkeypatch.setattr(
        "app.channels.providers.facebook_messenger.graph_send_message",
        AsyncMock(side_effect=FacebookOAuthError("recipient not reachable")),
    )
    result = await adapter.send_text(_cmd())
    assert not result.ok
    assert result.error_class == "provider_error"


def test_adapter_parse_delivery_receipt():
    adapter = _adapter()
    receipt = adapter.parse_receipt(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "recipient": {"id": "PAGE-1"},
                            "delivery": {"mids": ["m.7", "m.8"], "watermark": 1, "ts": 1700000000000},
                        }
                    ]
                }
            ]
        }
    )
    assert receipt is not None
    assert receipt.kind == "delivered"
    assert set(receipt.provider_message_ids) == {"m.7", "m.8"}
    assert receipt.account_key == "PAGE-1"


def test_adapter_parse_read_receipt():
    adapter = _adapter()
    receipt = adapter.parse_receipt(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "recipient": {"id": "PAGE-1"},
                            "read": {"watermark": 1, "ts": 1700000000000},
                        }
                    ]
                }
            ]
        }
    )
    # read-by-watermark carries no mids; the adapter returns None in V1
    # (mid-scoped read receipts are handled when mids are present).
    assert receipt is None


def test_adapter_no_receipt_returns_none():
    adapter = _adapter()
    assert adapter.parse_receipt({"entry": [{"messaging": [_msg_event(mid="m.1", text="hi")]}]}) is None


# ─── policy ─────────────────────────────────────────────────────────────────


def test_policy_window_open():
    now = datetime.now(timezone.utc)
    decision = evaluate_send_eligibility(
        last_inbound_at=now - timedelta(hours=1), now=now
    )
    assert decision.allowed
    assert decision.window_remaining_seconds is not None
    assert decision.window_remaining_seconds > 0


def test_policy_window_expired():
    now = datetime.now(timezone.utc)
    decision = evaluate_send_eligibility(
        last_inbound_at=now - MESSENGER_STANDARD_WINDOW - timedelta(seconds=1), now=now
    )
    assert not decision.allowed
    assert decision.reason == "window_expired"


def test_policy_no_inbound():
    assert not evaluate_send_eligibility(last_inbound_at=None).allowed


def test_policy_tz_naive_last_inbound_normalized():
    """Older rows may store tz-naive timestamps; the policy normalizes to UTC."""
    now = datetime.now(timezone.utc)
    naive = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert evaluate_send_eligibility(last_inbound_at=naive, now=now).allowed


# ─── webhook edge (signature-before-write) ──────────────────────────────────


class _FakeRequest:
    def __init__(self, body: bytes, headers: dict | None = None, query: dict | None = None) -> None:
        self._body = body
        self.headers = headers or {}
        self.query_params = query or {}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_webhook_post_rejects_invalid_signature_before_any_write(monkeypatch):
    """An invalid signature must 200-ack with zero side effects (no DB write,
    no ingress, no enqueue). Meta retries on non-2xx, so we ack-and-drop."""
    from app.api import webhooks

    # If any business path were reached, these would be called.
    monkeypatch.setattr(webhooks, "_resolve_active_facebook_page", AsyncMock(return_value=(None, None)))
    ingest = AsyncMock()
    monkeypatch.setattr("app.channels.ingress.ChannelIngressService.ingest", ingest)
    body = json.dumps({"entry": [{"messaging": [_msg_event(mid="m.1", text="hi")]}]}).encode()
    response = await webhooks.facebook_webhook(
        _FakeRequest(body, headers={"x-hub-signature-256": "sha256=" + "0" * 64}),
        db=MagicMock(),
    )
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "ignored"
    ingest.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_get_challenge_constant_time(monkeypatch):
    from types import SimpleNamespace

    from app.api import webhooks

    # Configure a known verify token so the challenge succeeds/fails deterministically.
    monkeypatch.setattr(
        webhooks,
        "_settings",
        SimpleNamespace(app_env="development", meta_webhook_verify_token="verify-me"),
    )
    response = await webhooks.facebook_webhook_verify(
        _FakeRequest(
            b"",
            query={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "CH-123"},
        )
    )
    assert response.status_code == 200
    assert json.loads(response.body)["hub.challenge"] == "CH-123"

    # Wrong verify token → 403.
    response = await webhooks.facebook_webhook_verify(
        _FakeRequest(
            b"",
            query={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "X"},
        )
    )
    assert response.status_code == 403

    # Wrong mode → 403.
    response = await webhooks.facebook_webhook_verify(
        _FakeRequest(b"", query={"hub.mode": "denied", "hub.verify_token": "verify-me", "hub.challenge": "X"})
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webhook_post_inactive_page_acks_without_turn(monkeypatch):
    """When no active Page is connected, the webhook acks as inactive — no
    bot turn is enqueued for a disconnected Page's traffic."""
    from types import SimpleNamespace

    from app.api import webhooks

    app_secret = "fb-app-secret-for-test"
    monkeypatch.setattr(
        webhooks,
        "_settings",
        SimpleNamespace(app_env="development", meta_app_secret=app_secret, meta_webhook_verify_token="t"),
    )
    monkeypatch.setattr(webhooks, "_resolve_active_facebook_page", AsyncMock(return_value=(None, None)))
    body = json.dumps({"entry": [{"messaging": [_msg_event(mid="m.1", text="hi")]}]}).encode()
    response = await webhooks.facebook_webhook(
        _FakeRequest(body, headers={"x-hub-signature-256": _sign(body, app_secret)}),
        db=MagicMock(),
    )
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "inactive"


# (The cross-Page receipt-isolation regression test lives in
# tests/integration/test_facebook_lifecycle.py where the integration_database
# fixture is visible.)
