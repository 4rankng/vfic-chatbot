"""PostgreSQL proofs for setup draft authority and atomic finalization."""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import pytest

from app.models.installation import (
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationSetupDraft,
    InstallationState,
)
from app.models.ingestion_template import (
    IngestionTemplate,
    IngestionTemplateVersion,
    TemplateVersionStatus,
)
from app.models.integration import IntegrationSetting
from app.schemas.installation import (
    InstallationSetupDraftFinalize,
    InstallationSetupDraftPayload,
    InstallationSetupDraftSave,
)
from app.services.errors import InstallationError
from app.services.installation.service import InstallationService
from app.services.installation.setup import InstallationSetupService
from tests.integration.test_installation_lifecycle import _seed_actor_and_persona
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


def _payload(persona_version) -> InstallationSetupDraftPayload:
    return InstallationSetupDraftPayload.model_validate(
        {
            "identity_branding": {
                "customer_identity": {"display_name": "Configured customer"},
                "branding": {"app_name": "Configured application"},
            },
            "regional_terminology": {
                "locale": "vi-VN",
                "timezone": "Asia/Ho_Chi_Minh",
                "currency": "VND",
                "terminology": {
                    "application": "Hồ sơ",
                    "candidate": "Ứng viên",
                    "conversation": "Hội thoại",
                    "job": "Việc làm",
                    "lead": "Khách tiềm năng",
                    "organization": "Doanh nghiệp",
                },
            },
            "pack_capabilities": {
                "pack_key": "recruitment",
                "capability_ids": [
                    "conversation",
                    "knowledge",
                    "candidate_intake",
                    "job_advisory",
                    "channel.zalo",
                ],
            },
            "workflow": {
                "workflow_policy": {
                    "workflow_id": "candidate_intake",
                    "workflow_version_id": str(persona_version._test_workflow_version_id),
                    "workflow_version_checksum": (persona_version._test_workflow_version_checksum),
                    "handoff_mode": "assisted",
                    "automation_enabled": False,
                }
            },
            "knowledge_templates": {"template_version_refs": []},
            "persona": {
                "persona_version_id": persona_version.id,
                "checksum": persona_version.checksum,
            },
            "providers_integrations": {
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
            },
        }
    )


async def test_saved_draft_without_immutable_state_projects_draft_lifecycle(integration_session):
    actor, persona_version = await _seed_actor_and_persona(integration_session)
    setup = InstallationSetupService(integration_session)
    saved = await setup.save(
        InstallationSetupDraftSave(payload=_payload(persona_version), expected_lock_version=0),
        actor.id,
    )

    assert saved.lock_version == 1
    assert saved.installation_lock_version == 0
    assert await integration_session.scalar(select(InstallationState)) is None
    public = await InstallationService(integration_session).runtime_view()
    admin = await InstallationService(integration_session).admin_view()
    assert public.lifecycle == "DRAFT"
    assert public.revision_id is None
    assert public.customer_identity is None
    assert admin.lifecycle == "DRAFT"


async def test_legacy_workflow_id_only_draft_requires_successor_before_finalize(
    integration_session,
):
    actor, persona_version = await _seed_actor_and_persona(integration_session)
    data = _payload(persona_version).model_dump(mode="json")
    data["workflow"]["workflow_policy"].pop("workflow_version_id")
    data["workflow"]["workflow_policy"].pop("workflow_version_checksum")
    setup = InstallationSetupService(integration_session)
    saved = await setup.save(
        InstallationSetupDraftSave(
            payload=InstallationSetupDraftPayload.model_validate(data),
            expected_lock_version=0,
        ),
        actor.id,
    )
    with pytest.raises(InstallationError) as exc_info:
        await setup.finalize(
            InstallationSetupDraftFinalize(
                expected_draft_lock_version=saved.lock_version,
                expected_installation_lock_version=0,
            ),
            actor.id,
        )
    assert any(issue["code"] == "WORKFLOW_VERSION_REQUIRED" for issue in exc_info.value.issues)


async def test_failed_finalize_rolls_back_revision_state_and_validation(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as save_session:
            actor, persona_version = await _seed_actor_and_persona(save_session)
            await InstallationSetupService(save_session).save(
                InstallationSetupDraftSave(
                    payload=_payload(persona_version), expected_lock_version=0
                ),
                actor.id,
            )
            actor_id = actor.id
        async with sessions() as remove_session:
            await remove_session.execute(delete(IntegrationSetting))
            await remove_session.commit()
        async with sessions() as finalize_session:
            with pytest.raises(InstallationError) as exc_info:
                await InstallationSetupService(finalize_session).finalize(
                    InstallationSetupDraftFinalize(
                        expected_draft_lock_version=1,
                        expected_installation_lock_version=0,
                    ),
                    actor_id,
                )

            assert exc_info.value.code == "INSTALLATION_VALIDATION_FAILED"
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestRevision)
                )
                == 0
            )
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestValidation)
                )
                == 0
            )
            assert await finalize_session.scalar(select(InstallationState)) is None
            draft = await finalize_session.scalar(select(InstallationSetupDraft))
            assert draft is not None
            assert draft.lock_version == 1
    finally:
        await _truncate(engine)
        await engine.dispose()


async def test_finalize_uses_both_tokens_and_ends_validated_without_activation(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as save_session:
            actor, persona_version = await _seed_actor_and_persona(save_session)
            await InstallationSetupService(save_session).save(
                InstallationSetupDraftSave(
                    payload=_payload(persona_version), expected_lock_version=0
                ),
                actor.id,
            )
            actor_id = actor.id
        async with sessions() as finalize_session:
            setup = InstallationSetupService(finalize_session)
            with pytest.raises(InstallationError) as stale:
                await setup.finalize(
                    InstallationSetupDraftFinalize(
                        expected_draft_lock_version=1,
                        expected_installation_lock_version=99,
                    ),
                    actor_id,
                )
            assert stale.value.code == "INSTALLATION_CONFLICT"
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestRevision)
                )
                == 0
            )

            revision = await setup.finalize(
                InstallationSetupDraftFinalize(
                    expected_draft_lock_version=1,
                    expected_installation_lock_version=0,
                ),
                actor_id,
            )
            state = await finalize_session.scalar(select(InstallationState))
            draft = await finalize_session.scalar(select(InstallationSetupDraft))
            assert state is not None
            assert state.lifecycle == "VALIDATED"
            assert state.active_revision_id is None
            assert state.current_revision_id == revision.id
            assert draft is not None and draft.lock_version == 2
            assert revision.authentication_policy_checksum is not None
            public = await InstallationService(finalize_session).runtime_view()
            assert public.lifecycle == "VALIDATED"
            assert public.revision_id is None
    finally:
        await _truncate(engine)
        await engine.dispose()


async def test_two_first_saves_produce_one_success_and_one_typed_conflict(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as seed_session:
            actor, persona_version = await _seed_actor_and_persona(seed_session)
            await seed_session.commit()
            actor_id = actor.id
            payload = _payload(persona_version)

        async def save():
            async with sessions() as session:
                try:
                    return await InstallationSetupService(session).save(
                        InstallationSetupDraftSave(
                            payload=payload,
                            expected_lock_version=0,
                        ),
                        actor_id,
                    )
                except InstallationError as exc:
                    await session.rollback()
                    return exc

        results = await asyncio.gather(save(), save())
        successes = [item for item in results if not isinstance(item, InstallationError)]
        conflicts = [item for item in results if isinstance(item, InstallationError)]
        assert len(successes) == 1
        assert successes[0].lock_version == 1
        assert len(conflicts) == 1
        assert conflicts[0].code == "INSTALLATION_CONFLICT"
    finally:
        await _truncate(engine)
        await engine.dispose()


async def test_finalize_rejects_mismatched_persona_checksum_without_partial_rows(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as save_session:
            actor, persona_version = await _seed_actor_and_persona(save_session)
            data = _payload(persona_version).model_dump(mode="json")
            data["persona"]["checksum"] = "f" * 64
            await InstallationSetupService(save_session).save(
                InstallationSetupDraftSave(
                    payload=InstallationSetupDraftPayload.model_validate(data),
                    expected_lock_version=0,
                ),
                actor.id,
            )
            actor_id = actor.id
        async with sessions() as finalize_session:
            with pytest.raises(InstallationError) as exc_info:
                await InstallationSetupService(finalize_session).finalize(
                    InstallationSetupDraftFinalize(
                        expected_draft_lock_version=1,
                        expected_installation_lock_version=0,
                    ),
                    actor_id,
                )
            assert any(
                issue["code"] == "PERSONA_CHECKSUM_MISMATCH" for issue in exc_info.value.issues
            )
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestRevision)
                )
                == 0
            )
    finally:
        await _truncate(engine)
        await engine.dispose()


async def test_finalize_rejects_nonpublished_template_without_partial_rows(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as save_session:
            actor, persona_version = await _seed_actor_and_persona(save_session)
            template = IngestionTemplate(
                template_key="draft-template",
                name="Draft template",
                vertical="recruitment",
                created_by=actor.id,
            )
            save_session.add(template)
            await save_session.flush()
            template_version = IngestionTemplateVersion(
                template_id=template.id,
                version_no=1,
                status=TemplateVersionStatus.DRAFT,
                definition={},
                checksum="e" * 64,
                created_by=actor.id,
            )
            save_session.add(template_version)
            await save_session.flush()
            data = _payload(persona_version).model_dump(mode="json")
            data["pack_capabilities"]["capability_ids"] = ["conversation", "knowledge"]
            data["knowledge_templates"]["template_version_refs"] = [
                {"version_id": str(template_version.id), "checksum": template_version.checksum}
            ]
            await InstallationSetupService(save_session).save(
                InstallationSetupDraftSave(
                    payload=InstallationSetupDraftPayload.model_validate(data),
                    expected_lock_version=0,
                ),
                actor.id,
            )
            actor_id = actor.id
        async with sessions() as finalize_session:
            with pytest.raises(InstallationError) as exc_info:
                await InstallationSetupService(finalize_session).finalize(
                    InstallationSetupDraftFinalize(
                        expected_draft_lock_version=1,
                        expected_installation_lock_version=0,
                    ),
                    actor_id,
                )
            assert any(
                issue["code"] == "TEMPLATE_VERSION_NOT_FOUND" for issue in exc_info.value.issues
            )
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestRevision)
                )
                == 0
            )
            assert (
                await finalize_session.scalar(
                    select(func.count()).select_from(InstallationManifestValidation)
                )
                == 0
            )
    finally:
        await _truncate(engine)
        await engine.dispose()


async def _truncate(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE audit_events, installation_setup_drafts, installation_state, "
                "installation_manifest_validations, installation_manifest_revisions, "
                "persona_versions, integration_settings, personas, users CASCADE"
            )
        )
