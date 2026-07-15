"""Focused contracts for the dormant generic Contact/Case kernel."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.dependencies import require_capability
from app.capabilities.recruitment.definition import PACK
from app.capabilities.registry import CapabilityRegistry
from app.schemas.case_workflows import CaseWorkflowCreate
from app.schemas.contacts import ContactCreate, ContactSummaryOut
from app.schemas.conversation import ConversationOut
from app.schemas.cases import CaseUpdate
from app.services.case_workflow_service import CaseWorkflowService, validate_case_attributes
from app.services.contact_service import ContactService


def _workflow(**overrides) -> CaseWorkflowCreate:
    payload = {
        "pack_key": "recruitment",
        "workflow_key": "candidate_intake",
        "label": "Candidate intake",
        "expected_previous_version_no": None,
        "stages": [
            {"key": "new", "label": "New", "position": 0, "is_initial": True},
            {"key": "done", "label": "Done", "position": 1, "is_terminal": True},
        ],
        "transitions": [{"from_stage_key": "new", "to_stage_key": "done"}],
        "tags": [{"key": "priority", "label": "Priority", "tone": "warning", "position": 0}],
        "case_attribute_schema": {
            "source": {"type": "string", "label": "Source", "required": True, "max_length": 20}
        },
    }
    payload.update(overrides)
    return CaseWorkflowCreate.model_validate(payload)


def test_workflow_checksum_is_canonical_across_input_order() -> None:
    first = _workflow()
    second = _workflow(
        stages=list(reversed(first.model_dump()["stages"])),
        tags=list(reversed(first.model_dump()["tags"])),
    )
    first_payload = CaseWorkflowService.canonical_payload(first, version_no=1)
    second_payload = CaseWorkflowService.canonical_payload(second, version_no=1)
    assert first_payload == second_payload


def test_workflow_rejects_unreachable_stage_and_operational_attribute_authority() -> None:
    service = CaseWorkflowService(AsyncMock())
    body = _workflow(
        stages=[
            {"key": "new", "label": "New", "position": 0, "is_initial": True},
            {"key": "orphan", "label": "Orphan", "position": 1, "is_terminal": True},
        ],
        transitions=[],
    )
    with pytest.raises(ValueError, match="reachable"):
        service._validate_definition(body)

    with pytest.raises(ValueError, match="terminal stage"):
        service._validate_definition(
            _workflow(
                stages=[{"key": "new", "label": "New", "position": 0, "is_initial": True}],
                transitions=[],
            )
        )

    with pytest.raises(ValidationError, match="operational-authority"):
        _workflow(case_attribute_schema={"stage": {"type": "string", "label": "Stage"}})


def test_case_attributes_are_closed_and_required() -> None:
    schema = {
        key: value.model_dump(exclude_none=True)
        for key, value in _workflow().case_attribute_schema.items()
    }
    validate_case_attributes(schema, {"source": "zalo"})
    with pytest.raises(ValueError, match="unknown"):
        validate_case_attributes(schema, {"source": "zalo", "stock": 3})
    with pytest.raises(ValueError, match="missing"):
        validate_case_attributes(schema, {})


def test_contact_has_no_generic_attributes_contract() -> None:
    with pytest.raises(ValidationError):
        ContactCreate.model_validate({"display_name": "A", "attributes": {"x": 1}})


def test_conversation_projection_is_backward_compatible_and_nullable() -> None:
    now = datetime.now(UTC)
    old = ConversationOut.model_validate(
        {
            "id": uuid.uuid4(),
            "zalo_chat_id": "candidate",
            "mode": "BOT",
            "status": "OPEN",
            "needs_human": False,
            "version": 1,
            "unread_count": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert old.contact_id is None and old.channel_identity_id is None and old.contact is None

    contact_id = uuid.uuid4()
    projected = ContactSummaryOut.model_validate(
        SimpleNamespace(
            id=contact_id,
            display_name="Candidate",
            primary_email=None,
            primary_phone=None,
            avatar_url=None,
            primary_channel=None,
        )
    )
    assert projected.id == contact_id


def test_registry_rejects_cycles_and_owner_collisions() -> None:
    from app.capabilities.contracts import CapabilityDefinition, IndustryPackDefinition

    with pytest.raises(ValueError, match="cycle"):
        CapabilityRegistry(
            capabilities=(CapabilityDefinition("a", ("b",)), CapabilityDefinition("b", ("a",))),
            packs=(IndustryPackDefinition("pack", "1", ("a", "b"), "1"),),
        )
    with pytest.raises(ValueError, match="multiple dashboard"):
        CapabilityRegistry(
            capabilities=(
                CapabilityDefinition("a", dashboard_owner=True),
                CapabilityDefinition("b", dashboard_owner=True),
            ),
            packs=(IndustryPackDefinition("pack", "1", ("a", "b"), "1"),),
        )


def test_shipped_pack_remains_runtime_dormant() -> None:
    assert PACK.runtime_ready is False
    assert replace(PACK, runtime_ready=False).runtime_ready is False


async def test_dormant_capability_dependency_fails_closed_with_authenticated_404() -> None:
    dependency = require_capability("conversation")
    active = SimpleNamespace(revision=SimpleNamespace(capability_ids=["knowledge"]))
    with pytest.raises(HTTPException) as exc_info:
        await dependency(active)
    assert exc_info.value.status_code == 404

    allowed = SimpleNamespace(revision=SimpleNamespace(capability_ids=["conversation"]))
    assert await dependency(allowed) is allowed

    with pytest.raises(ValueError, match="unknown capability"):
        require_capability("unknown.module")


def test_case_patch_rejects_explicit_null_attributes_but_allows_omission() -> None:
    with pytest.raises(ValidationError):
        CaseUpdate.model_validate({"version": 1, "attributes": None})
    omitted = CaseUpdate.model_validate({"version": 1, "subject": "Updated"})
    assert "attributes" not in omitted.model_fields_set


async def test_adoption_requires_explicit_nonlegacy_configured_account_key() -> None:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="oa:user-1",
        zalo_channel="oa",
        contact_id=None,
        channel_identity_id=None,
    )
    db = MagicMock()
    db.flush = AsyncMock()
    service = ContactService(db)
    for account_key in ("", "   ", "legacy:zalo:oa"):
        with pytest.raises(ValueError, match="configured channel account key"):
            await service.adopt_conversation(conversation, account_key=account_key)

    identity = SimpleNamespace(id=uuid.uuid4(), contact_id=uuid.uuid4())
    service.resolve_channel_identity = AsyncMock(return_value=identity)
    adopted = await service.adopt_conversation(
        conversation, account_key="zalo.oa.primary", actor_id=None
    )
    assert adopted is identity
    service.resolve_channel_identity.assert_awaited_once_with(
        provider="zalo",
        account_key="zalo.oa.primary",
        external_id="user-1",
        actor_id=None,
    )
