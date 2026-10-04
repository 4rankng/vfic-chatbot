"""PostgreSQL proof for immutable installation activation and rollback generations."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import delete, select

import app.services.installation.lifecycle as installation_lifecycle_module  # binds the fingerprint cache helpers
from app.capabilities import CapabilityDefinition, CapabilityRegistry, IndustryPackDefinition
from app.capabilities.recruitment.definition import CAPABILITIES, PACK
from app.models.installation import InstallationState
from app.models.integration import IntegrationSetting
from app.models.lead import Lead
from app.models.case_workflow import CaseWorkflowStage, CaseWorkflowVersion
from app.models.user import Role, User
from app.schemas.installation import InstallationRevisionCreate
from app.shared.domain.errors import InstallationError
from app.services.installation.hashing import sha256_json
from app.services.installation.service import InstallationService

pytestmark = pytest.mark.integration
_WORKFLOW_PINS: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}


def _runtime_ready_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        capabilities=CAPABILITIES,
        packs=(replace(PACK, runtime_ready=True),),
    )


def _revision_body(
    workflow_pin: uuid.UUID, *, display_name: str, expected_lock_version: int = 0
) -> InstallationRevisionCreate:
    workflow_version_id, workflow_version_checksum = _WORKFLOW_PINS[workflow_pin]
    return InstallationRevisionCreate(
        expected_lock_version=expected_lock_version,
        pack_key="recruitment",
        customer_identity={"display_name": display_name},
        branding={"app_name": "Configured app"},
        locale="vi-VN",
        timezone="Asia/Ho_Chi_Minh",
        currency="VND",
        terminology={
            "application": "Hồ sơ",
            "candidate": "Ứng viên",
            "conversation": "Hội thoại",
            "job": "Việc làm",
            "lead": "Khách tiềm năng",
            "organization": "Doanh nghiệp",
        },
        workflow_policy={
            "workflow_id": "candidate_intake",
            "workflow_version_id": workflow_version_id,
            "workflow_version_checksum": workflow_version_checksum,
            "handoff_mode": "assisted",
            "automation_enabled": True,
        },
        capability_ids=["conversation", "candidate_intake"],
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
        authentication_policy={"email_password_enabled": True},
    )


async def _seed_actor_and_workflow_pin(integration_session) -> tuple[User, uuid.UUID]:
    """Seed the actor plus a workflow version, and return a handle for the pin.

    The revision used to pin a ``persona_versions`` row, which gave the test a
    second thing to seed and a per-revision id to thread through. The persona is
    a code constant now and the manifest pins it by checksum, so this returns a
    plain token that only keys ``_WORKFLOW_PINS`` for the request body.
    """
    actor = User(
        email=f"phase2-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    integration_session.add(actor)
    await integration_session.flush()
    workflow_pin = uuid.uuid4()
    workflow_version = CaseWorkflowVersion(
        pack_key="recruitment",
        workflow_key="candidate_intake",
        version_no=1,
        label="Candidate intake",
        schema_version=1,
        case_attribute_schema={},
        checksum=sha256_json(
            {
                "pack_key": "recruitment",
                "workflow_key": "candidate_intake",
                "version_no": 1,
                "stages": ["new"],
            }
        ),
        created_by=actor.id,
    )
    integration_session.add(workflow_version)
    await integration_session.flush()
    integration_session.add(
        CaseWorkflowStage(
            workflow_version_id=workflow_version.id,
            stage_key="new",
            label="New",
            position=0,
            is_initial=True,
            is_terminal=False,
        )
    )
    _WORKFLOW_PINS[workflow_pin] = (workflow_version.id, workflow_version.checksum)
    integration_session.add_all(
        [
            IntegrationSetting(
                key="openrouter_api_key",
                encrypted_value="encrypted-test-value",
                updated_by=actor.id,
            ),
            IntegrationSetting(
                key="openrouter_enable",
                encrypted_value="true",
                updated_by=actor.id,
            ),
        ]
    )
    await integration_session.flush()
    return actor, workflow_pin


async def test_revision_activation_rollback_suspend_and_resume_are_generation_safe(
    integration_session,
    monkeypatch,
):
    actor, workflow_pin = await _seed_actor_and_workflow_pin(integration_session)
    registry = _runtime_ready_registry()
    service = InstallationService(integration_session, registry=registry)

    initial = await service.runtime_view()
    assert initial.lifecycle == "UNCONFIGURED"
    assert await integration_session.scalar(select(InstallationState)) is None

    first = await service.create_revision(
        _revision_body(workflow_pin, display_name="Customer one"), actor.id
    )
    await service.validate_revision(first.id, actor.id)

    async def cache_outage() -> None:
        raise RuntimeError("simulated Redis outage")

    monkeypatch.setattr(installation_lifecycle_module, "invalidate_installation_cache", cache_outage)
    first_active = await service.activate_revision(first.id, actor.id)
    assert first_active.fingerprint.authority_generation == 1

    # Cache-first resolution: a hit for the exact current identity is served
    # as-is (see the dedicated cache-first test below); any advanced identity
    # must re-derive from the database instead of trusting the entry.
    async def forged_cache(revision_id, generation):
        if revision_id == first.id and generation == first_active.fingerprint.authority_generation:
            return replace(first_active.fingerprint, manifest_checksum="b" * 64)
        return None

    monkeypatch.setattr(installation_lifecycle_module, "get_cached_fingerprint", forged_cache)
    cache_checked = await service.require_active()
    assert cache_checked.fingerprint.manifest_checksum == "b" * 64

    current_lock = (await service.admin_view()).lock_version
    second = await service.create_revision(
        _revision_body(
            workflow_pin,
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
        delete(IntegrationSetting).where(IntegrationSetting.key == "openrouter_api_key")
    )
    await integration_session.commit()
    drifted = await service.runtime_view()
    assert drifted.readiness_code == "VALIDATION_REQUIRED"
    with pytest.raises(InstallationError) as inactive:
        await service.require_active()
    assert inactive.value.code == "INSTALLATION_NOT_ACTIVE"


async def test_resolve_active_serves_a_warm_hit_without_revalidating_and_rederives_on_cutover(
    integration_session,
    monkeypatch,
):
    actor, workflow_pin = await _seed_actor_and_workflow_pin(integration_session)
    registry = _runtime_ready_registry()
    service = InstallationService(integration_session, registry=registry)
    first = await service.create_revision(
        _revision_body(workflow_pin, display_name="Cache first"), actor.id
    )
    await service.validate_revision(first.id, actor.id)
    first_active = await service.activate_revision(first.id, actor.id)

    async def warm_hit(revision_id, generation):
        if revision_id == first.id and generation == first_active.fingerprint.authority_generation:
            return replace(first_active.fingerprint, manifest_checksum="b" * 64)
        return None

    monkeypatch.setattr(installation_lifecycle_module, "get_cached_fingerprint", warm_hit)
    validation_calls = 0
    real_validation = InstallationService._validation_is_current

    async def counting_validation(*args, **kwargs):
        nonlocal validation_calls
        validation_calls += 1
        return await real_validation(*args, **kwargs)

    monkeypatch.setattr(InstallationService, "_validation_is_current", counting_validation)

    served = await service.require_active()
    assert served is not None
    assert served.revision.id == first.id
    assert served.fingerprint.manifest_checksum == "b" * 64
    assert validation_calls == 0

    current_lock = (await service.admin_view()).lock_version
    second = await service.create_revision(
        _revision_body(
            workflow_pin,
            display_name="After cutover",
            expected_lock_version=current_lock,
        ),
        actor.id,
    )
    await service.validate_revision(second.id, actor.id)
    second_active = await service.activate_revision(second.id, actor.id)

    rederived = await service.require_active()
    assert rederived.revision.id == second.id
    assert rederived.fingerprint.checksum() == second_active.fingerprint.checksum()
    assert rederived.fingerprint.manifest_checksum != "b" * 64
    assert validation_calls > 0


async def test_stale_admin_save_is_rejected_by_lock_version(integration_session):
    actor, workflow_pin = await _seed_actor_and_workflow_pin(integration_session)
    service = InstallationService(integration_session)
    await service.create_revision(
        _revision_body(workflow_pin, display_name="First save"), actor.id
    )

    with pytest.raises(InstallationError) as conflict:
        await service.create_revision(
            _revision_body(workflow_pin, display_name="Stale save"), actor.id
        )

    assert conflict.value.code == "INSTALLATION_CONFLICT"


async def test_operational_data_created_after_draft_blocks_incompatible_first_activation(
    integration_session,
):
    actor, workflow_pin = await _seed_actor_and_workflow_pin(integration_session)
    registry = CapabilityRegistry(
        capabilities=(CapabilityDefinition("conversation"),),
        packs=(
            IndustryPackDefinition(
                key="unsupported-pack",
                version="1",
                capability_ids=("conversation",),
                kernel_abi="1",
                workflow_ids=("candidate_intake",),
                terminology_keys=(
                    "application",
                    "candidate",
                    "conversation",
                    "job",
                    "lead",
                    "organization",
                ),
                runtime_ready=True,
            ),
        ),
    )
    service = InstallationService(integration_session, registry=registry)
    unsupported_workflow = CaseWorkflowVersion(
        pack_key="unsupported-pack",
        workflow_key="candidate_intake",
        version_no=1,
        label="Unsupported intake",
        schema_version=1,
        case_attribute_schema={},
        checksum=sha256_json({"pack_key": "unsupported-pack", "version_no": 1}),
        created_by=actor.id,
    )
    integration_session.add(unsupported_workflow)
    await integration_session.flush()
    body = _revision_body(workflow_pin, display_name="Unsupported customer").model_copy(
        update={
            "pack_key": "unsupported-pack",
            "capability_ids": ["conversation"],
            "workflow_policy": _revision_body(
                workflow_pin, display_name="unused"
            ).workflow_policy.model_copy(
                update={
                    "workflow_version_id": unsupported_workflow.id,
                    "workflow_version_checksum": unsupported_workflow.checksum,
                }
            ),
        }
    )
    revision = await service.create_revision(body, actor.id)
    await service.validate_revision(revision.id, actor.id)

    integration_session.add(Lead(name="Recruitment record"))
    await integration_session.flush()

    with pytest.raises(InstallationError) as exc_info:
        await service.activate_revision(revision.id, actor.id)
    assert exc_info.value.code == "INSTALLATION_PACK_LOCKED"


async def test_real_recruitment_pack_activates_without_registry_override(
    integration_session,
):
    """The shipped recruitment pack is activation-ready.

    This is the regression test for the ``runtime_ready=True`` unlock: a full
    create → validate → activate cycle succeeds against the default capability
    registry (the real production pack), with no ``_runtime_ready_registry``
    fixture override. An admin can activate a recruitment installation without
    the bot being blocked by a dormant-pack rejection.
    """
    actor, workflow_pin = await _seed_actor_and_workflow_pin(integration_session)
    # Default registry = the real shipped packs. No override.
    service = InstallationService(integration_session)

    revision = await service.create_revision(
        _revision_body(workflow_pin, display_name="Real pack customer"), actor.id
    )
    await service.validate_revision(revision.id, actor.id)

    active = await service.activate_revision(revision.id, actor.id)
    assert active.fingerprint.authority_generation == 1
    assert active.revision.pack_key == "recruitment"

    # The runtime now resolves this installation as active, stamping turns.
    resolved = await service.resolve_active()
    assert resolved is not None
    assert resolved.revision.id == revision.id
