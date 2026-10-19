"""ODS settings group: resolve / admin view / update behavior.

Follows the typed-double convention of ``test_email_digest_settings.py`` —
the stubs implement only the narrow duck-typed surface the mixin exercises.
"""

# pyright: reportArgumentType=false

import pytest

from app.services.integration_settings import (
    ODS_API_KEY,
    ODS_AUTH_KEY,
    ODS_AUTH_USER,
    ODS_ENABLED,
    ODS_RECIPIENTS,
    ODS_SERVICE_NAME,
    IntegrationSettingsService,
    OdsRuntimeConfig,
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


async def test_resolve_defaults_to_off_and_empty():
    service = _service(_MutableDb())
    config = await service.resolve_ods()
    assert config == OdsRuntimeConfig(
        service_name="", auth_user="", auth_key="", recipients=(), enabled=False
    )


async def test_resolve_stored_first_and_parses_rows():
    db = _MutableDb(
        [
            _Row(ODS_SERVICE_NAME, "CloudFone"),
            _Row(ODS_AUTH_USER, "ods-user"),
            _Row(ODS_AUTH_KEY, _encrypted_row("cf-key-123"), True),
            _Row(ODS_RECIPIENTS, "ops@vp.vn, hr@vp.vn, ops@vp.vn"),
            _Row(ODS_ENABLED, "1"),
        ]
    )
    config = await _service(db).resolve_ods()
    assert config.service_name == "CloudFone"
    assert config.auth_user == "ods-user"
    assert config.auth_key == "cf-key-123"
    assert config.recipients == ("ops@vp.vn", "hr@vp.vn")
    assert config.enabled is True


async def test_resolve_falls_back_to_the_legacy_single_key_row():
    """A pre-spec deployment's stored api_key rides as AuthKey until re-saved."""
    db = _MutableDb([_Row(ODS_API_KEY, _encrypted_row("legacy-key"), True)])
    config = await _service(db).resolve_ods()
    assert config.auth_key == "legacy-key"


async def test_resolve_prefers_the_spec_key_over_the_legacy_row():
    db = _MutableDb(
        [
            _Row(ODS_API_KEY, _encrypted_row("legacy-key"), True),
            _Row(ODS_AUTH_KEY, _encrypted_row("spec-key"), True),
        ]
    )
    assert (await _service(db).resolve_ods()).auth_key == "spec-key"


async def test_admin_view_masks_the_key_and_reports_effective_state():
    db = _MutableDb(
        [
            _Row(ODS_SERVICE_NAME, "CloudFone"),
            _Row(ODS_AUTH_USER, "ods-user"),
            _Row(ODS_AUTH_KEY, _encrypted_row("cf-key-123"), True),
            _Row(ODS_RECIPIENTS, "ops@vp.vn"),
            _Row(ODS_ENABLED, "1"),
        ]
    )
    view = await _service(db).admin_ods_view()
    assert view["service_name"] == "CloudFone"
    assert view["auth_user"] == "ods-user"
    assert view["auth_key"] == {"configured": True, "preview": f"{len('cf-key-123')} ký tự"}
    assert "cf-key-123" not in str(view)
    assert view["recipients"] == ["ops@vp.vn"]
    assert view["enabled"] is True


async def test_admin_view_reports_off_without_recipients_even_when_enabled():
    db = _MutableDb(
        [
            _Row(ODS_SERVICE_NAME, "CloudFone"),
            _Row(ODS_AUTH_USER, "ods-user"),
            _Row(ODS_AUTH_KEY, _encrypted_row("cf-key-123"), True),
        ]
    )
    view = await _service(db).admin_ods_view()
    assert view["enabled"] is False


async def test_admin_view_reports_off_with_a_missing_credential():
    db = _MutableDb(
        [
            _Row(ODS_SERVICE_NAME, "CloudFone"),
            _Row(ODS_AUTH_USER, "ods-user"),
            _Row(ODS_RECIPIENTS, "ops@vp.vn"),
            _Row(ODS_ENABLED, "1"),
        ]
    )
    view = await _service(db).admin_ods_view()
    assert view["enabled"] is False


async def test_update_stores_credentials_recipients_and_toggle():
    from app.services.integration_settings import IntegrationSettingsCipher

    db = _MutableDb()

    view = await _service(db).update_ods(
        {
            "service_name": "CloudFone",
            "auth_user": "ods-user",
            "auth_key": "new-key",
            "recipients": ["a@x.com", "a@x.com"],
            "enabled": True,
        },
        actor_id="admin-1",
    )
    assert view["service_name"] == "CloudFone"
    assert view["auth_user"] == "ods-user"
    assert view["auth_key"]["configured"] is True
    assert view["recipients"] == ["a@x.com"]
    assert view["enabled"] is True
    stored = {row.key: row for row in db.rows.values()}
    assert stored[ODS_SERVICE_NAME].is_secret is False
    assert stored[ODS_AUTH_USER].is_secret is False
    assert stored[ODS_AUTH_KEY].is_secret is True
    # The key is encrypted at rest — recoverable only through the cipher.
    assert (
        IntegrationSettingsCipher(_Settings()).decrypt(stored[ODS_AUTH_KEY].encrypted_value)
        == "new-key"
    )
    assert stored[ODS_RECIPIENTS].encrypted_value == "a@x.com"
    assert stored[ODS_ENABLED].encrypted_value == "1"
    assert db.commit_count == 1


async def test_update_omitted_credentials_keep_stored_values():
    from app.services.integration_settings import IntegrationSettingsCipher

    db = _MutableDb(
        [
            _Row(ODS_AUTH_KEY, _encrypted_row("old-key"), True),
            _Row(ODS_AUTH_USER, "old-user"),
        ]
    )
    await _service(db).update_ods({"enabled": True}, actor_id=None)
    assert (
        IntegrationSettingsCipher(_Settings()).decrypt(db.rows[ODS_AUTH_KEY].encrypted_value)
        == "old-key"
    )
    assert db.rows[ODS_AUTH_USER].encrypted_value == "old-user"


async def test_update_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        await _service(_MutableDb()).update_ods({"last_sent_at": "x"}, actor_id=None)


async def test_update_rejects_invalid_recipients():
    with pytest.raises(ValidationError):
        await _service(_MutableDb()).update_ods({"recipients": ["khong-phai-email"]}, actor_id=None)


async def test_update_off_writes_explicit_zero():
    db = _MutableDb([_Row(ODS_ENABLED, "1")])
    await _service(db).update_ods({"enabled": False}, actor_id=None)
    assert db.rows[ODS_ENABLED].encrypted_value == "0"
