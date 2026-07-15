"""PostgreSQL proof for immutable installation activation and rollback generations."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import delete, select

import app.services.installation.service as installation_service_module
from app.capabilities import CapabilityDefinition, CapabilityRegistry, IndustryPackDefinition
from app.capabilities.recruitment.definition import CAPABILITIES, PACK
from app.models.installation import InstallationState
from app.models.integration import IntegrationSetting
from app.models.lead import Lead
from app.models.persona import Persona, PersonaVersion
from app.models.user import Role, User
from app.schemas.installation import InstallationRevisionCreate
from app.services.errors import InstallationError
from app.services.installation.hashing import sha256_json
from app.services.installation.service import InstallationService

pytestmark = pytest.mark.integration


def _runtime_ready_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        capabilities=CAPABILITIES,
        packs=(replace(PACK, runtime_ready=True),),
    )


def _revision_body(
    persona_version_id: uuid.UUID, *, display_name: str, expected_lock_version: int = 0
) -> InstallationRevisionCreate:
    return InstallationRevisionCreate(
        expected_lock_version=expected_lock_version,
        pack_key="recruitment",
        customer_identity={"display_name": display_name},
        branding={"logo_url": "/customer/logo.svg"},
        locale="vi-VN",
        timezone="Asia/Ho_Chi_Minh",
        currency="VND",
        terminology={"lead": "Ứng viên"},
        workflow_policy={
            "workflow_id": "candidate_intake",
            "handoff_mode": "assisted",
            "automation_enabled": True,
        },
        capability_ids=list(PACK.capability_ids),
        persona_version_id=persona_version_id,
        template_version_refs=[],
        provider_policy={
            "chat_integration_key": "openrouter",
            "chat_model": "minimax/minimax-m2",
            "embedding_integration_key": "openrouter",
            "embedding_model": "google/gemini-embedding-001",
            "temperature": 0.2,
            "max_output_tokens": 2048,
        },
        integration_requirements=[{"key": "openrouter"}],
    )


async def _seed_actor_and_persona(integration_session) -> tuple[User, PersonaVersion]:
    actor = User(
        email=f"phase2-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    persona = Persona(
        name="Configured voice",
        slug=f"configured-{uuid.uuid4().hex}",
        body_md="Configured persona body",
        followup_rules={},
        created_by=None,
    )
    integration_session.add_all([actor, persona])
    await integration_session.flush()
    persona_version = PersonaVersion(
        persona_id=persona.id,
        version_no=1,
        body_md=persona.body_md,
        followup_rules=persona.followup_rules,
        checksum=sha256_json(
            {"body_md": persona.body_md, "followup_rules": persona.followup_rules}
        ),
        created_by=actor.id,
    )
    integration_session.add(persona_version)
    integration_session.add(
        IntegrationSetting(
            key="openrouter",
            encrypted_value="encrypted-test-value",
            updated_by=actor.id,
        )
    )
    await integration_session.flush()
    return actor, persona_version


async def test_revision_activation_rollback_suspend_and_resume_are_generation_safe(
    integration_session,
    monkeypatch,
):
    actor, persona_version = await _seed_actor_and_persona(integration_session)
    registry = _runtime_ready_registry()
    service = InstallationService(integration_session, registry=registry)

    initial = await service.runtime_view()
    assert initial.lifecycle == "UNCONFIGURED"
    assert await integration_session.scalar(select(InstallationState)) is None

    first = await service.create_revision(
        _revision_body(persona_version.id, display_name="Customer one"), actor.id
    )
    await service.validate_revision(first.id, actor.id)

    with pytest.raises(InstallationError) as blocked:
        await InstallationService(integration_session).activate_revision(first.id, actor.id)
    assert blocked.value.code == "INSTALLATION_RUNTIME_NOT_READY"

    async def cache_outage() -> None:
        raise RuntimeError("simulated Redis outage")

    monkeypatch.setattr(installation_service_module, "invalidate_installation_cache", cache_outage)
    first_active = await service.activate_revision(first.id, actor.id)
    assert first_active.fingerprint.authority_generation == 1

    async def forged_cache(_revision_id, _generation):
        return replace(first_active.fingerprint, manifest_checksum="b" * 64)

    monkeypatch.setattr(installation_service_module, "get_cached_fingerprint", forged_cache)
    cache_checked = await service.require_active()
    assert cache_checked.fingerprint.manifest_checksum != "b" * 64

    current_lock = (await service.admin_view()).lock_version
    second = await service.create_revision(
        _revision_body(
            persona_version.id,
            display_name="Customer two",
            expected_lock_version=current_lock,
        ),
        actor.id,
    )
    await service.validate_revision(second.id, actor.id)
    second_active = await service.activate_revision(second.id, actor.id)
    assert second_active.fingerprint.authority_generation == 2
    assert second_active.revision.id == second.id

    rolled_back = await service.rollback_revision(first.id, actor.id)
    assert rolled_back.fingerprint.authority_generation == 3
    assert rolled_back.revision.id == first.id
    assert rolled_back.fingerprint.checksum() != first_active.fingerprint.checksum()

    suspended = await service.suspend(actor.id)
    assert suspended.lifecycle == "SUSPENDED"
    assert suspended.authority_generation == 4
    assert await service.resolve_active() is None

    resumed = await service.resume(actor.id)
    assert resumed.fingerprint.authority_generation == 5
    assert resumed.revision.id == first.id
    await service.assert_current(resumed.fingerprint)

    public = await service.runtime_view()
    assert public.lifecycle == "ACTIVE"
    assert public.readiness_code == "READY"
    assert public.customer_identity == {"display_name": "Customer one"}
    assert "provider_policy" not in public.model_dump()

    await integration_session.execute(
        delete(IntegrationSetting).where(IntegrationSetting.key == "openrouter")
    )
    await integration_session.commit()
    drifted = await service.runtime_view()
    assert drifted.readiness_code == "VALIDATION_REQUIRED"
    with pytest.raises(InstallationError) as inactive:
        await service.require_active()
    assert inactive.value.code == "INSTALLATION_NOT_ACTIVE"


async def test_stale_admin_save_is_rejected_by_lock_version(integration_session):
    actor, persona_version = await _seed_actor_and_persona(integration_session)
    service = InstallationService(integration_session)
    await service.create_revision(
        _revision_body(persona_version.id, display_name="First save"), actor.id
    )

    with pytest.raises(InstallationError) as conflict:
        await service.create_revision(
            _revision_body(persona_version.id, display_name="Stale save"), actor.id
        )

    assert conflict.value.code == "INSTALLATION_CONFLICT"


async def test_operational_data_created_after_draft_blocks_incompatible_first_activation(
    integration_session,
):
    actor, persona_version = await _seed_actor_and_persona(integration_session)
    registry = CapabilityRegistry(
        capabilities=(CapabilityDefinition("conversation"),),
        packs=(
            IndustryPackDefinition(
                key="product_advisory",
                version="1",
                capability_ids=("conversation",),
                kernel_abi="1",
                runtime_ready=True,
            ),
        ),
    )
    service = InstallationService(integration_session, registry=registry)
    body = _revision_body(persona_version.id, display_name="Product customer").model_copy(
        update={"pack_key": "product_advisory", "capability_ids": ["conversation"]}
    )
    revision = await service.create_revision(body, actor.id)
    await service.validate_revision(revision.id, actor.id)

    integration_session.add(Lead(name="Recruitment record"))
    await integration_session.flush()

    with pytest.raises(InstallationError) as exc_info:
        await service.activate_revision(revision.id, actor.id)
    assert exc_info.value.code == "INSTALLATION_PACK_LOCKED"
