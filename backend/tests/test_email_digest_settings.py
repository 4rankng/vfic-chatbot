"""Email-digest settings group: parse/resolve/admin-view/update behavior.

Follows the typed-double convention of ``test_integration_settings.py`` — the
stubs implement only the narrow duck-typed surface the mixin exercises.
"""

# pyright: reportArgumentType=false

from datetime import datetime, timezone

import pytest

from app.services.integration_settings import (
    EMAIL_DIGEST_ENABLED,
    EMAIL_DIGEST_FREQUENCY,
    EMAIL_DIGEST_LAST_SENT_AT,
    EMAIL_DIGEST_RECIPIENTS,
    EMAIL_DIGEST_RESEND_API_KEY,
    EMAIL_DIGEST_SEND_TIME,
    DEFAULT_FREQUENCY,
    DEFAULT_SEND_TIME,
    IntegrationSettingsService,
    parse_recipients,
)
from app.shared.domain.errors import ValidationError


class _Settings:
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    resend_api_key = "env-resend-key"


class _Row:
    def __init__(self, key: str, encrypted_value: str, is_secret: bool = False) -> None:
        self.key = key
        self.encrypted_value = encrypted_value
        self.is_secret = is_secret
        self.updated_by = None


class _ScalarResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _MutableDb:
    def __init__(self, rows=None) -> None:
        self.rows = {row.key: row for row in (rows or [])}
        self.added: list = []
        self.commit_count = 0

    async def scalars(self, _query):
        return _ScalarResult(list(self.rows.values()))

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        # Settings rows are keyed; audit events are not — keep both visible.
        key = getattr(row, "key", None)
        if key is not None:
            self.rows[key] = row
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _service(db: _MutableDb) -> IntegrationSettingsService:
    return IntegrationSettingsService(db, settings=_Settings())


def _encrypted_row(plain: str) -> str:
    from app.services.integration_settings import IntegrationSettingsCipher

    cipher = IntegrationSettingsCipher(_Settings())
    return cipher.encrypt(plain)


def test_parse_recipients_normalizes_and_dedupes():
    assert parse_recipients("a@x.com, b@y.com\na@x.com") == ["a@x.com", "b@y.com"]
    assert parse_recipients(["a@x.com ", "", "b@y.com"]) == ["a@x.com", "b@y.com"]
    assert parse_recipients(None) == []
    assert parse_recipients("") == []


def test_parse_recipients_rejects_invalid():
    with pytest.raises(ValidationError):
        parse_recipients("khong-phai-email")
    with pytest.raises(ValidationError):
        parse_recipients(["a@x.com", "bad@"])


async def test_resolve_defaults_to_env_key_and_daily_9am():
    service = _service(_MutableDb())
    config = await service.resolve_email_digest()
    assert config.resend_api_key == "env-resend-key"
    assert config.recipients == ()
    assert config.frequency == DEFAULT_FREQUENCY
    assert config.send_time == DEFAULT_SEND_TIME
    assert config.last_sent_at is None


async def test_resolve_stored_first_and_parses_rows():
    db = _MutableDb(
        [
            _Row(EMAIL_DIGEST_RESEND_API_KEY, _encrypted_row("stored-key"), True),
            _Row(EMAIL_DIGEST_RECIPIENTS, "hr@vp.vn, ops@vp.vn"),
            _Row(EMAIL_DIGEST_FREQUENCY, "weekly"),
            _Row(EMAIL_DIGEST_SEND_TIME, "07:30"),
            _Row(
                EMAIL_DIGEST_LAST_SENT_AT,
                "2026-10-01T02:00:00+00:00",
            ),
        ]
    )
    config = await _service(db).resolve_email_digest()
    assert config.resend_api_key == "stored-key"
    assert config.recipients == ("hr@vp.vn", "ops@vp.vn")
    assert config.frequency == "weekly"
    assert config.send_time == "07:30"
    assert config.last_sent_at == datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)


async def test_admin_view_masks_the_key_and_reports_enabled():
    db = _MutableDb([_Row(EMAIL_DIGEST_RESEND_API_KEY, _encrypted_row("stored-key"), True)])
    view = await _service(db).admin_email_digest_view()
    assert view["resend_api_key"]["configured"] is True
    assert "stored-key" not in str(view["resend_api_key"])
    assert view["enabled"] is False  # no recipients yet
    assert view["last_sent_at"] is None


async def test_update_roundtrip_commits_and_audits():
    db = _MutableDb()
    view = await _service(db).update_email_digest(
        {
            "recipients": ["hr@vp.vn", "boss@vp.vn"],
            "frequency": "weekly",
            "send_time": "09:30",
        },
        actor_id="admin-1",
    )
    assert view["recipients"] == ["hr@vp.vn", "boss@vp.vn"]
    assert view["frequency"] == "weekly"
    assert view["send_time"] == "09:30"
    assert view["enabled"] is True
    assert db.commit_count == 1
    audit_rows = [row for row in db.added if getattr(row, "action", "") == "update_email_digest_settings"]
    assert len(audit_rows) == 1


async def test_update_stores_key_encrypted():
    db = _MutableDb()
    view = await _service(db).update_email_digest(
        {"resend_api_key": "fresh-key"},
        actor_id="admin-1",
    )
    assert view["resend_api_key"]["configured"] is True
    row = db.rows[EMAIL_DIGEST_RESEND_API_KEY]
    assert "fresh-key" not in row.encrypted_value


async def test_update_rejects_invalid_values():
    db = _MutableDb()
    with pytest.raises(ValidationError):
        await _service(db).update_email_digest({"recipients": "bad@"}, actor_id="a")
    with pytest.raises(ValidationError):
        await _service(db).update_email_digest({"frequency": "hourly"}, actor_id="a")
    with pytest.raises(ValidationError):
        await _service(db).update_email_digest(
            {"send_time": "9:15"}, actor_id="a"
        )
    with pytest.raises(ValidationError):
        await _service(db).update_email_digest({"last_sent_at": "x"}, actor_id="a")
    with pytest.raises(ValidationError):
        await _service(db).update_email_digest({"unknown_field": "x"}, actor_id="a")
    assert db.commit_count == 0


async def test_out_model_accepts_admin_view():
    """The API projection round-trips the mixin view (send_time not send_hour)."""
    from app.schemas.integrations import EmailDigestSettingsOut

    db = _MutableDb([_Row(EMAIL_DIGEST_RESEND_API_KEY, _encrypted_row("stored-key"), True)])
    view = await _service(db).admin_email_digest_view()
    out = EmailDigestSettingsOut.model_validate(view)
    assert out.send_time == "09:00"
    assert out.resend_api_key.configured is True
    assert out.enabled is False


async def test_update_accepts_the_settings_page_payload():
    """Regression: the console PUT speaks API field names, not KV key names.

    The first prod PUT 422'd on every field because the update path validated
    against the namespaced KV keys ("email_digest_*") instead of the schema
    names the frontend sends.
    """
    db = _MutableDb()
    view = await _service(db).update_email_digest(
        {
            "resend_api_key": "re_live_key",
            "recipients": ["hr@vp.vn"],
            "frequency": "daily",
            "send_time": "09:00",
            "enabled": True,
        },
        actor_id="admin-1",
    )
    assert view["resend_api_key"]["configured"] is True
    assert view["recipients"] == ["hr@vp.vn"]
    assert view["frequency"] == "daily"
    assert view["send_time"] == "09:00"
    assert view["enabled"] is True
    row = db.rows[EMAIL_DIGEST_RESEND_API_KEY]
    assert "re_live_key" not in row.encrypted_value
    assert db.commit_count == 1


async def test_enabled_toggle_roundtrip():
    db = _MutableDb()
    off = await _service(db).update_email_digest({"enabled": False}, actor_id="a")
    assert off["enabled"] is False  # recipients also empty, but the toggle itself stored
    assert db.rows[EMAIL_DIGEST_ENABLED].encrypted_value == "0"
    on = await _service(db).update_email_digest({"enabled": True}, actor_id="a")
    assert on["enabled"] is False  # toggle on, but no recipients yet
    assert db.rows[EMAIL_DIGEST_ENABLED].encrypted_value == "1"


async def test_resolve_respects_stored_toggle():
    db = _MutableDb([_Row(EMAIL_DIGEST_ENABLED, "0"), _Row(EMAIL_DIGEST_RECIPIENTS, "hr@vp.vn")])
    config = await _service(db).resolve_email_digest()
    assert config.enabled is False
    assert config.recipients == ("hr@vp.vn",)
