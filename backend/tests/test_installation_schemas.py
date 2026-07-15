"""Pure Pydantic contract tests for installation input and public runtime output."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.installation import InstallationRevisionCreate, InstallationRuntimeOut


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
}

SAFE_RUNTIME_FIELDS = {
    "lifecycle",
    "authority_generation",
    "revision_id",
    "pack_key",
    "customer_identity",
    "branding",
    "locale",
    "timezone",
    "currency",
    "terminology",
    "capability_ids",
    "readiness_code",
}


def _active_runtime_payload() -> dict[str, object]:
    return {
        "lifecycle": "ACTIVE",
        "authority_generation": 9,
        "revision_id": "00000000-0000-0000-0000-000000000009",
        "pack_key": "recruitment",
        "customer_identity": {"display_name": "Doanh nghiệp kiểm thử"},
        "branding": {"logo_url": "/assets/customer-logo.svg"},
        "locale": "vi-VN",
        "timezone": "Asia/Ho_Chi_Minh",
        "currency": "VND",
        "terminology": {"lead": "Ứng viên"},
        "capability_ids": ["conversation", "candidate_intake"],
        "readiness_code": "READY",
    }


def _valid_revision_payload() -> dict[str, object]:
    return {
        "expected_lock_version": 0,
        "pack_key": "recruitment",
        "customer_identity": {"display_name": "Customer"},
        "branding": {},
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


def test_locale_accepts_script_and_region_bcp47_form() -> None:
    payload = _valid_revision_payload()
    payload["locale"] = "zh-Hant-TW"
    assert InstallationRevisionCreate.model_validate(payload).locale == "zh-Hant-TW"


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
