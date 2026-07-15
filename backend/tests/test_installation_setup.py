"""Pure contracts for setup draft validation and the code-owned catalog."""

from __future__ import annotations

from unittest.mock import AsyncMock
import uuid

import pytest

from app.schemas.installation import InstallationSetupDraftPayload
from app.services.errors import InstallationError
from app.services.installation.setup import InstallationSetupService


async def test_catalog_is_code_owned_and_contains_no_selected_defaults() -> None:
    catalog = await InstallationSetupService(AsyncMock()).catalog()

    assert catalog.schema_version == 1
    assert catalog.integration_keys == ["minimax", "openrouter", "zalo"]
    assert catalog.authentication_methods == ["email_password"]
    assert catalog.locales == ["vi-VN"]
    assert catalog.packs[0].key == "recruitment"
    assert catalog.packs[0].runtime_ready is False
    assert "candidate_intake" in catalog.packs[0].workflow_ids
    assert all(not hasattr(pack, "selected") for pack in catalog.packs)


def test_draft_rejects_unknown_provider_reference_before_database_write() -> None:
    payload = InstallationSetupDraftPayload.model_validate(
        {
            "providers_integrations": {
                "provider_policy": {
                    "chat_integration_key": "filesystem.provider",
                    "chat_model": "model-1",
                    "embedding_integration_key": "openrouter",
                    "embedding_model": "embedding-1",
                    "temperature": 0.2,
                    "max_output_tokens": 1024,
                },
                "integration_requirements": [],
                "authentication_policy": {"email_password_enabled": True},
            }
        }
    )

    with pytest.raises(InstallationError) as exc_info:
        InstallationSetupService(AsyncMock())._validate_authoring_choices(
            payload, "DRAFT", require_complete=False
        )

    assert exc_info.value.code == "INSTALLATION_VALIDATION_FAILED"
    assert exc_info.value.issues[0]["code"] == "INTEGRATION_REFERENCE_INVALID"


@pytest.mark.parametrize(
    "value",
    ["sk-live-credential", "github_pat_private", "-----BEGIN PRIVATE KEY-----"],
)
def test_secret_shaped_values_are_rejected_without_flagging_normal_contact_data(value: str) -> None:
    assert InstallationSetupService._contains_secret_value({"display_name": value}) is True
    assert (
        InstallationSetupService._contains_secret_value(
            {"support_email": "support@example.test", "support_phone": "+84 123 456 789"}
        )
        is False
    )


def test_complete_setup_requires_every_selected_pack_terminology_label() -> None:
    payload = InstallationSetupDraftPayload.model_validate(
        {
            "identity_branding": {
                "customer_identity": {"display_name": "Customer"},
                "branding": {"app_name": "Application"},
            },
            "regional_terminology": {
                "locale": "vi-VN",
                "timezone": "Asia/Ho_Chi_Minh",
                "currency": "VND",
                "terminology": {
                    "application": "Application",
                    "candidate": "Candidate",
                    "conversation": "Conversation",
                    "job": "Job",
                    "lead": "Lead",
                },
            },
            "pack_capabilities": {"pack_key": "recruitment", "capability_ids": ["conversation"]},
            "workflow": {
                "workflow_policy": {
                    "workflow_id": "candidate_intake",
                    "handoff_mode": "manual",
                    "automation_enabled": False,
                }
            },
            "knowledge_templates": {"template_version_refs": []},
            "persona": {"persona_version_id": uuid.uuid4(), "checksum": "a" * 64},
            "providers_integrations": {
                "provider_policy": {
                    "chat_integration_key": "openrouter",
                    "chat_model": "model-1",
                    "embedding_integration_key": "openrouter",
                    "embedding_model": "embedding-1",
                    "temperature": 0,
                    "max_output_tokens": 1,
                },
                "integration_requirements": [],
                "authentication_policy": {"email_password_enabled": True},
            },
        }
    )

    with pytest.raises(InstallationError) as exc_info:
        InstallationSetupService(AsyncMock())._validate_authoring_choices(
            payload, "DRAFT", require_complete=True
        )

    assert any(issue["code"] == "TERMINOLOGY_REQUIRED" for issue in exc_info.value.issues)
