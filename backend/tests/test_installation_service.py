"""Pure service contracts for unconfigured and fail-closed installation states."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.installation import InstallationRevisionCreate
from app.services.errors import InstallationError
from app.services.installation.service import InstallationService


def _body(*, pack_key: str = "recruitment") -> InstallationRevisionCreate:
    return InstallationRevisionCreate(
        expected_lock_version=0,
        pack_key=pack_key,
        customer_identity={"display_name": "Customer"},
        branding={"app_name": "Configured app"},
        locale="vi-VN",
        timezone="Asia/Ho_Chi_Minh",
        currency="VND",
        terminology={
            "application": "Application",
            "candidate": "Candidate",
            "conversation": "Conversation",
            "job": "Job",
            "lead": "Lead",
            "organization": "Organization",
        },
        workflow_policy={
            "workflow_id": "candidate_intake",
            "handoff_mode": "assisted",
            "automation_enabled": True,
        },
        capability_ids=[],
        persona_version_id=uuid.uuid4(),
        template_version_refs=[],
        provider_policy={
            "chat_integration_key": "openrouter",
            "chat_model": "minimax/minimax-m2",
            "embedding_integration_key": "openrouter",
            "embedding_model": "google/gemini-embedding-001",
            "temperature": 0.2,
            "max_output_tokens": 2048,
        },
        integration_requirements=[],
        authentication_policy={"email_password_enabled": True},
    )


async def test_absent_state_reads_unconfigured_without_writing() -> None:
    db = AsyncMock()
    service = InstallationService(db)
    service.repo = SimpleNamespace(
        acquire_authority_lock=AsyncMock(),
        get_state=AsyncMock(return_value=None),
        has_legacy_workspace=AsyncMock(return_value=False),
    )

    view = await service.runtime_view()

    assert view.lifecycle == "UNCONFIGURED"
    assert view.readiness_code == "SETUP_REQUIRED"
    assert view.legacy_workspace is False
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_existing_pre_installation_workspace_is_marked_for_legacy_ui_compatibility() -> None:
    service = InstallationService(AsyncMock())
    service.repo = SimpleNamespace(
        get_state=AsyncMock(return_value=None),
        has_legacy_workspace=AsyncMock(return_value=True),
    )

    view = await service.runtime_view()

    assert view.lifecycle == "UNCONFIGURED"
    assert view.readiness_code == "SETUP_REQUIRED"
    assert view.legacy_workspace is True


async def test_unknown_pack_is_a_typed_validation_failure_before_any_write() -> None:
    db = AsyncMock()
    service = InstallationService(db)
    service.repo = SimpleNamespace(
        acquire_authority_lock=AsyncMock(), get_state=AsyncMock(return_value=None)
    )

    with pytest.raises(InstallationError) as exc_info:
        await service.create_revision(_body(pack_key="database.import.path"), uuid.uuid4())

    assert exc_info.value.code == "INSTALLATION_VALIDATION_FAILED"
    assert exc_info.value.status_code == 422
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_historical_revision_without_authentication_authority_requires_upgrade() -> None:
    service = InstallationService(AsyncMock())
    lifecycle, readiness = await service._runtime_readiness(
        SimpleNamespace(lifecycle="ACTIVE"),
        SimpleNamespace(authentication_policy=None, authentication_policy_checksum=None),
    )

    assert lifecycle == "UPGRADE_REQUIRED"
    assert readiness == "UPGRADE_REQUIRED"


@pytest.mark.parametrize(
    "policy",
    [
        {"api_key": "plaintext"},
        {"nested": {"password": "plaintext"}},
        {"providers": [{"token": "plaintext"}]},
        {"branding": {"password": "plaintext"}},
        {"customer_identity": {"credential": "plaintext"}},
        {"openrouter_api_key": "plaintext"},
        {"oauthToken": "plaintext"},
    ],
)
def test_plaintext_secret_keys_are_rejected_in_nested_settings(
    policy: dict[str, object],
) -> None:
    assert InstallationService._contains_secret_key(policy) is True
    assert InstallationService._contains_secret_key({"integration_ref": "openrouter"}) is False


def test_public_mapping_is_allowlisted_even_for_legacy_rows() -> None:
    projected = InstallationService._public_mapping(
        {
            "display_name": "Safe customer",
            "openrouter_api_key": "must-not-leak",
            "internal_notes": "must-not-leak",
        },
        {"display_name"},
    )

    assert projected == {"display_name": "Safe customer"}
