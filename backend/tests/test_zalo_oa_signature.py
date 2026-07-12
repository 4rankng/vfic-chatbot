"""Pure tests for the shared Zalo OA signature verifier (no IO)."""

from __future__ import annotations

import hashlib
import json

from app.services.zalo_oa_signature import compute_mac, to_json, verify_signature


def _payload() -> dict:
    return {
        "app_id": "app-1",
        "timestamp": "1700000000",
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"text": "hi", "msg_id": "m1"},
    }


def test_verifier_accepts_documented_digest_and_labels_it():
    payload = _payload()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = compute_mac("app-1", raw.decode("utf-8"), "1700000000", "secret")

    result = verify_signature(
        signature=f"sha256={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
        timestamp_header="1700000000",
    )
    assert result.verified is True
    assert result.matched_label == "sha256(app_id+raw_body+header_ts+secret)"


def test_verifier_uses_timestamp_header_not_body_field():
    """Zalo signs with the X-ZEvent-Timestamp HEADER value, not the body field."""
    payload = _payload()
    payload["timestamp"] = "body-ts-not-used"
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header_ts = "1700000000000"
    digest = hashlib.sha256(b"app-1" + raw + header_ts.encode() + b"secret").hexdigest()

    result = verify_signature(
        signature=f"mac={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
        timestamp_header=header_ts,
    )
    assert result.verified is True
    assert "header_ts" in result.matched_label


def test_verifier_accepts_bare_hex_signature():
    payload = _payload()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = compute_mac("app-1", raw.decode("utf-8"), "1700000000", "secret")

    result = verify_signature(
        signature=digest,  # no mac=/sha256= prefix
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
        timestamp_header="1700000000",
    )
    assert result.verified is True


def test_verifier_rejects_wrong_secret():
    payload = _payload()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = compute_mac("app-1", raw.decode("utf-8"), "1700000000", "WRONG-SECRET")

    result = verify_signature(
        signature=f"sha256={digest}",
        raw=raw,
        payload=payload,
        app_id="app-1",
        secret_key="secret",
        timestamp_header="1700000000",
    )
    assert result.verified is False
    assert result.matched_label is None


def test_verifier_rejects_missing_inputs():
    payload = _payload()
    raw = json.dumps(payload).encode("utf-8")
    assert not verify_signature(
        signature="", raw=raw, payload=payload, app_id="app-1", secret_key="secret"
    ).verified
    assert not verify_signature(
        signature="abc", raw=raw, payload=payload, app_id="", secret_key="secret"
    ).verified
    assert not verify_signature(
        signature="abc", raw=raw, payload=payload, app_id="app-1", secret_key=""
    ).verified


def test_to_json_is_compact_and_preserves_non_ascii_order():
    assert to_json({"b": 2, "a": 1}) == '{"b":2,"a":1}'
    assert to_json({"t": "Xin chào"}) == '{"t":"Xin chào"}'
