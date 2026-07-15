"""Pure Pydantic contract tests for installation input and public runtime output."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.installation import (
    InstallationRevisionCreate,
    InstallationRevisionOut,
    InstallationRuntimeOut,
    InstallationSetupDraftPayload,
)


REQUIRED_BUSINESS_FIELDS = {
    "expected_lock_version",
    "pack_key",
    "customer_identity",
    "branding",
    "locale",
    "timezone",
    "currency",
    "terminology",
    "workflow_policy",
    "capability_ids",
    "persona_version_id",
    "template_version_refs",
    "provider_policy",
    "integration_requirements",
    "authentication_policy",
}

SAFE_RUNTIME_FIELDS = {
    "lifecycle",
    "authority_generation",
    "revision_id",
    "pack_key",
    "pack_version",
    "pack_contract_hash",
    "manifest_checksum",
    "customer_identity",
    "branding",
    "locale",
    "timezone",
    "currency",
    "terminology",
    "capability_ids",
    "readiness_code",
    "legacy_workspace",
    "schema_version",
}


def _active_runtime_payload() -> dict[str, object]:
    return {
        "lifecycle": "ACTIVE",
        "authority_generation": 9,
        "revision_id": "00000000-0000-0000-0000-000000000009",
        "pack_key": "recruitment",
        "pack_version": "1",
        "pack_contract_hash": "a" * 64,
        "manifest_checksum": "b" * 64,
        "customer_identity": {"display_name": "Doanh nghiệp kiểm thử"},
        "branding": {"app_name": "Configured app"},
        "locale": "vi-VN",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "terminology": {"lead": "Ứng viên"},
        "capability_ids": ["conversation", "candidate_intake"],
        "readiness_code": "READY",
        "legacy_workspace": False,
    }


def _valid_revision_payload() -> dict[str, object]:
    return {
        "expected_lock_version": 0,
        "pack_key": "recruitment",
        "customer_identity": {"display_name": "Customer"},
        "branding": {"app_name": "Configured app"},
        "locale": "vi-VN",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "terminology": {},
        "workflow_policy": {
            "workflow_id": "candidate_intake",
            "handoff_mode": "assisted",
            "automation_enabled": True,
        },
        "capability_ids": [],
        "persona_version_id": str(uuid.uuid4()),
        "template_version_refs": [],
        "provider_policy": {
            "chat_integration_key": "openrouter",
            "chat_model": "minimax/minimax-m2",
            "embedding_integration_key": "openrouter",
            "embedding_model": "google/gemini-embedding-001",
            "temperature": 0.2,
            "max_output_tokens": 2048,
        },
        "integration_requirements": [],
        "authentication_policy": {"email_password_enabled": True},
    }


def test_revision_create_requires_every_business_configuration_field() -> None:
    assert REQUIRED_BUSINESS_FIELDS <= set(InstallationRevisionCreate.model_fields)
    assert all(
        InstallationRevisionCreate.model_fields[field].is_required()
        for field in REQUIRED_BUSINESS_FIELDS
    )

    with pytest.raises(ValidationError) as exc_info:
        InstallationRevisionCreate.model_validate({})

    missing_fields = {
        str(error["loc"][0]) for error in exc_info.value.errors() if error["type"] == "missing"
    }
    assert REQUIRED_BUSINESS_FIELDS <= missing_fields


def test_runtime_projection_has_exactly_the_approved_safe_fields() -> None:
    assert set(InstallationRuntimeOut.model_fields) == SAFE_RUNTIME_FIELDS

    runtime = InstallationRuntimeOut.model_validate(_active_runtime_payload())
    dumped = runtime.model_dump(mode="json")

    assert set(dumped) == SAFE_RUNTIME_FIELDS
    assert dumped["authority_generation"] == 9
    assert dumped["capability_ids"] == ["conversation", "candidate_intake"]


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value"),
    [
        ("body_md", "Nội dung persona riêng tư"),
        (
            "provider_policy",
            {"provider": "private-provider", "model": "private-model", "api_key": "secret"},
        ),
    ],
)
def test_runtime_projection_rejects_private_persona_and_provider_fields(
    unsafe_field: str,
    unsafe_value: object,
) -> None:
    payload = _active_runtime_payload()
    payload[unsafe_field] = unsafe_value

    with pytest.raises(ValidationError) as exc_info:
        InstallationRuntimeOut.model_validate(payload)

    assert any(error["loc"] == (unsafe_field,) for error in exc_info.value.errors())


def test_runtime_serialization_contains_no_persona_body_or_provider_values() -> None:
    serialized = json.dumps(
        InstallationRuntimeOut.model_validate(_active_runtime_payload()).model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "body_md" not in serialized
    assert "provider_policy" not in serialized
    assert "private-provider" not in serialized
    assert "private-model" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pack_key", "Python.Import.Path"),
        ("locale", "vietnamese"),
        ("timezone", "Mars/Olympus_Mons"),
        ("currency", "dong"),
    ],
)
def test_revision_rejects_noncanonical_identifiers(field: str, value: str) -> None:
    payload = _valid_revision_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


def test_template_reference_requires_lowercase_sha256() -> None:
    payload = _valid_revision_payload()
    payload["template_version_refs"] = [{"version_id": str(uuid.uuid4()), "checksum": "Z" * 64}]
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


def test_conflicting_duplicate_template_checksums_are_rejected_for_every_authoring_path() -> None:
    version_id = str(uuid.uuid4())
    conflicting_refs = [
        {"version_id": version_id, "checksum": "a" * 64},
        {"version_id": version_id, "checksum": "b" * 64},
    ]
    revision_payload = _valid_revision_payload()
    revision_payload["template_version_refs"] = conflicting_refs
    with pytest.raises(ValidationError) as direct_error:
        InstallationRevisionCreate.model_validate(revision_payload)
    assert any(error["loc"] == ("template_version_refs",) for error in direct_error.value.errors())

    with pytest.raises(ValidationError) as draft_error:
        InstallationSetupDraftPayload.model_validate(
            {"knowledge_templates": {"template_version_refs": conflicting_refs}}
        )
    assert any(
        error["loc"] == ("knowledge_templates", "template_version_refs")
        for error in draft_error.value.errors()
    )


def test_locale_rejects_well_formed_but_unshipped_catalog() -> None:
    payload = _valid_revision_payload()
    payload["locale"] = "zh-Hant-TW"
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


def test_branding_requires_explicit_nonblank_app_name_and_rejects_asset_urls() -> None:
    payload = _valid_revision_payload()
    payload["branding"] = {"app_name": "   "}
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)

    payload["branding"] = {"app_name": "Configured", "logo_url": "https://example.test/a.png"}
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("support_email", "not-an-email"),
        ("website_url", "javascript:alert(1)"),
    ],
)
def test_customer_identity_matches_public_bootstrap_validation(field: str, value: str) -> None:
    payload = _valid_revision_payload()
    payload["customer_identity"] = {"display_name": "Customer", field: value}
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


def test_historical_revision_output_accepts_null_authentication_authority() -> None:
    payload = {
        "id": str(uuid.uuid4()),
        "revision_no": 1,
        "predecessor_id": None,
        "pack_key": "recruitment",
        "pack_version": "1",
        "pack_contract_hash": "a" * 64,
        "manifest_checksum": "b" * 64,
        "customer_identity": {"display_name": "Historical customer"},
        "branding": {},
        "locale": "vi-VN",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "terminology": {},
        "workflow_policy": {},
        "workflow_policy_checksum": "c" * 64,
        "capability_ids": [],
        "persona_version_id": str(uuid.uuid4()),
        "template_version_refs": [],
        "provider_policy": {},
        "provider_policy_checksum": "d" * 64,
        "integration_requirements": [],
        "authentication_policy": None,
        "authentication_policy_checksum": None,
        "created_by": None,
        "created_at": datetime.now(UTC),
    }

    output = InstallationRevisionOut.model_validate(payload)
    assert output.authentication_policy is None
    assert output.authentication_policy_checksum is None


def test_currency_must_exist_in_current_iso4217_catalog() -> None:
    payload = _valid_revision_payload()
    payload["currency"] = "ZZZ"
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_policy", {"workflow_id": "candidate", "secret": "plaintext"}),
        ("provider_policy", {"value": "sk-live-secret"}),
    ],
)
def test_policy_objects_are_closed_and_cannot_accept_arbitrary_secret_storage(
    field: str, value: dict[str, object]
) -> None:
    payload = _valid_revision_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        InstallationRevisionCreate.model_validate(payload)
