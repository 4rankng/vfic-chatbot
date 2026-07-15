"""PostgreSQL proof for the exact 0043/0044 migration boundary."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.audit import AuditEvent
from app.models.case import Case, FollowupStatus
from app.models.case_workflow import (
    CaseTagDefinition,
    CaseWorkflowStage,
    CaseWorkflowTransition,
    CaseWorkflowVersion,
)
from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation
from app.models.installation import (
    InstallationManifestRevision,
    InstallationManifestValidation,
)
from app.models.persona import Persona, PersonaVersion
from app.models.user import Role, User
from app.schemas.case_workflows import CaseWorkflowCreate
from app.schemas.cases import CaseCreate, CaseFollowupCreate, CaseUpdate
from app.schemas.contacts import ChannelIdentityCreate, ContactCreate, ContactUpdate
from app.services.case_service import CaseService
from app.services.case_workflow_service import CaseWorkflowService
from app.services.contact_service import ContactService
from app.services.errors import ConflictError, ForbiddenError, NotFoundError

from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase

pytestmark = pytest.mark.integration


def _alembic(
    database: IntegrationDatabase, command: str, target: str, *, check: bool = True
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    return subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), command, target],
        cwd=BACKEND_DIR,
        env=env,
        check=check,
        timeout=120,
        capture_output=True,
        text=True,
    )


async def test_empty_0043_0044_roundtrip_and_populated_refusal(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0043_installation_setup_draft")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('public.contacts')")) is None
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            assert (
                await connection.scalar(text("SELECT to_regclass('public.contacts')"))
                == "contacts"
            )
            assert await connection.scalar(text("SELECT count(*) FROM contacts")) == 0
    finally:
        await engine.dispose()

    _alembic(integration_database, "downgrade", "0043_installation_setup_draft")
    _alembic(integration_database, "upgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO contacts DEFAULT VALUES"))
    finally:
        await engine.dispose()
    refused = _alembic(
        integration_database, "downgrade", "0043_installation_setup_draft", check=False
    )
    assert refused.returncode != 0
    assert "refusing to downgrade populated generic kernel" in refused.stderr
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM contacts"))
    finally:
        await engine.dispose()


async def test_0044_downgrade_refuses_linked_conversations(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url)
    conversation_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    try:
        async with engine.begin() as connection:
            contact_id = await connection.scalar(
                text("INSERT INTO contacts DEFAULT VALUES RETURNING id")
            )
            identity_id = await connection.scalar(
                text(
                    "INSERT INTO contact_channel_identities "
                    "(contact_id, provider, account_key, external_id) "
                    "VALUES (:contact_id, 'zalo', 'oa.primary', :external_id) RETURNING id"
                ),
                {"contact_id": contact_id, "external_id": uuid.uuid4().hex},
            )
            conversation_id = await connection.scalar(
                text(
                    "INSERT INTO conversations "
                    "(zalo_chat_id, zalo_channel, contact_id, channel_identity_id) "
                    "VALUES (:chat_id, 'oa', :contact_id, :identity_id) RETURNING id"
                ),
                {
                    "chat_id": f"oa:{uuid.uuid4().hex}",
                    "contact_id": contact_id,
                    "identity_id": identity_id,
                },
            )

        refused = _alembic(
            integration_database, "downgrade", "0043_installation_setup_draft", check=False
        )
        assert refused.returncode != 0
        assert "refusing to downgrade populated generic kernel" in refused.stderr
    finally:
        if conversation_id is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    delete(Conversation).where(Conversation.id == conversation_id)
                )
                await connection.execute(
                    delete(ContactChannelIdentity).where(
                        ContactChannelIdentity.id == identity_id
                    )
                )
                await connection.execute(delete(Contact).where(Contact.id == contact_id))
        await engine.dispose()


async def test_0044_downgrade_refuses_installation_validation_workflow_pin(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    persona_version_id: uuid.UUID | None = None
    revision_id: uuid.UUID | None = None
    validation_id: uuid.UUID | None = None
    checksum = "a" * 64
    try:
        async with sessions() as session:
            actor = User(
                email=f"pin-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.admin,
            )
            persona = Persona(
                name="Pin test",
                slug=f"pin-{uuid.uuid4().hex}",
                body_md="Pin test",
                followup_rules={},
                created_by=actor.id,
            )
            persona_version = PersonaVersion(
                persona_id=persona.id,
                version_no=1,
                body_md="Pin test",
                followup_rules={},
                checksum=checksum,
                created_by=actor.id,
            )
            session.add_all([actor, persona])
            await session.flush()
            persona_version.persona_id = persona.id
            persona_version.created_by = actor.id
            session.add(persona_version)
            await session.flush()
            revision = InstallationManifestRevision(
                pack_key="recruitment",
                pack_version="1",
                pack_contract_hash=checksum,
                manifest_checksum=checksum,
                customer_identity={},
                branding={},
                locale="vi-VN",
                timezone="Asia/Ho_Chi_Minh",
                currency="VND",
                terminology={},
                workflow_policy={},
                workflow_policy_checksum=checksum,
                capability_ids=[],
                persona_version_id=persona_version.id,
                template_version_refs=[],
                provider_policy={},
                provider_policy_checksum=checksum,
                integration_requirements=[],
                created_by=actor.id,
            )
            session.add(revision)
            await session.flush()
            validation = InstallationManifestValidation(
                revision_id=revision.id,
                validator_version="1",
                is_valid=True,
                issues=[],
                reference_snapshot={},
                manifest_checksum=checksum,
                pack_contract_hash=checksum,
                persona_checksum=checksum,
                workflow_policy_checksum=checksum,
                provider_policy_checksum=checksum,
                workflow_version_checksum=checksum,
                template_checksums={},
                active_kb_vector=[],
                validated_by=actor.id,
            )
            session.add(validation)
            await session.commit()
            user_id, persona_id, persona_version_id = actor.id, persona.id, persona_version.id
            revision_id, validation_id = revision.id, validation.id

        refused = _alembic(
            integration_database, "downgrade", "0043_installation_setup_draft", check=False
        )
        assert refused.returncode != 0
        assert "refusing to downgrade populated generic kernel" in refused.stderr
    finally:
        if validation_id is not None:
            async with engine.begin() as connection:
                for table, trigger in (
                    (
                        "installation_manifest_validations",
                        "installation_manifest_validations_immutable",
                    ),
                    (
                        "installation_manifest_revisions",
                        "installation_manifest_revisions_immutable",
                    ),
                    ("persona_versions", "persona_versions_immutable"),
                ):
                    await connection.execute(
                        text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
                    )
                await connection.execute(
                    delete(InstallationManifestValidation).where(
                        InstallationManifestValidation.id == validation_id
                    )
                )
                await connection.execute(
                    delete(InstallationManifestRevision).where(
                        InstallationManifestRevision.id == revision_id
                    )
                )
                await connection.execute(
                    delete(PersonaVersion).where(PersonaVersion.id == persona_version_id)
                )
                await connection.execute(delete(Persona).where(Persona.id == persona_id))
                await connection.execute(delete(User).where(User.id == user_id))
                for table, trigger in (
                    (
                        "installation_manifest_validations",
                        "installation_manifest_validations_immutable",
                    ),
                    (
                        "installation_manifest_revisions",
                        "installation_manifest_revisions_immutable",
                    ),
                    ("persona_versions", "persona_versions_immutable"),
                ):
                    await connection.execute(
                        text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
                    )
        await engine.dispose()

def _workflow() -> CaseWorkflowCreate:
    return CaseWorkflowCreate.model_validate(
        {
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
                "source": {"type": "string", "label": "Source", "required": True}
            },
        }
    )


async def _cleanup_committed_case_kernel(
    engine,
    *,
    workflow_id: uuid.UUID,
    user_ids: tuple[uuid.UUID, ...],
    contact_ids: tuple[uuid.UUID, ...],
    conversation_ids: tuple[uuid.UUID, ...] = (),
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(AuditEvent).where(
                (AuditEvent.actor_id.in_(user_ids))
                | (AuditEvent.target_id.in_([str(workflow_id), *(str(item) for item in contact_ids)]))
            )
        )
        await connection.execute(
            delete(Case).where(Case.workflow_version_id == workflow_id)
        )
        if conversation_ids:
            await connection.execute(
                delete(Conversation).where(Conversation.id.in_(conversation_ids))
            )
        await connection.execute(
            delete(ContactChannelIdentity).where(
                ContactChannelIdentity.contact_id.in_(contact_ids)
            )
        )
        await connection.execute(delete(Contact).where(Contact.id.in_(contact_ids)))
        await connection.execute(
            text(
                "ALTER TABLE case_workflow_versions DISABLE TRIGGER "
                "case_workflow_versions_immutable"
            )
        )
        for table, trigger in (
            ("case_workflow_transitions", "case_workflow_transitions_immutable"),
            ("case_tag_definitions", "case_tag_definitions_immutable"),
            ("case_workflow_stages", "case_workflow_stages_immutable"),
        ):
            await connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
        await connection.execute(
            delete(CaseWorkflowTransition).where(
                CaseWorkflowTransition.workflow_version_id == workflow_id
            )
        )
        await connection.execute(
            delete(CaseTagDefinition).where(
                CaseTagDefinition.workflow_version_id == workflow_id
            )
        )
        await connection.execute(
            delete(CaseWorkflowStage).where(
                CaseWorkflowStage.workflow_version_id == workflow_id
            )
        )
        await connection.execute(
            delete(CaseWorkflowVersion).where(CaseWorkflowVersion.id == workflow_id)
        )
        await connection.execute(delete(User).where(User.id.in_(user_ids)))
        await connection.execute(
            text(
                "ALTER TABLE case_workflow_versions ENABLE TRIGGER "
                "case_workflow_versions_immutable"
            )
        )
        for table, trigger in (
            ("case_workflow_transitions", "case_workflow_transitions_immutable"),
            ("case_tag_definitions", "case_tag_definitions_immutable"),
            ("case_workflow_stages", "case_workflow_stages_immutable"),
        ):
            await connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))


async def test_workflow_contact_case_lifecycle_is_pinned_and_audited(
    integration_session, monkeypatch
) -> None:
    monkeypatch.setattr(integration_session, "commit", integration_session.flush)
    actor = User(
        email=f"kernel-{uuid.uuid4().hex}@example.test",
        password_hash="unused",
        role=Role.admin,
    )
    integration_session.add(actor)
    await integration_session.flush()
    workflow_service = CaseWorkflowService(integration_session)
    workflow = await workflow_service.create(_workflow(), actor.id)
    contact = await ContactService(integration_session).create(
        ContactCreate(display_name="Candidate"), actor
    )
    case_service = CaseService(integration_session)
    case = await case_service.create(
        CaseCreate(
            contact_id=contact.id,
            workflow_version_id=workflow.id,
            workflow_checksum=workflow.checksum,
            attributes={"source": "zalo"},
        ),
        actor,
    )
    transitioned = await case_service.transition(
        case, target="done", version=case.version, actor=actor
    )
    assert transitioned.lifecycle == "CLOSED"
    assert transitioned.closed_at is not None
    assert transitioned.workflow_checksum == workflow.checksum
    audit_actions = set(await integration_session.scalars(select(AuditEvent.action)))
    assert {
        "publish_case_workflow",
        "create_contact",
        "create_case",
        "transition_case",
    } <= audit_actions


async def test_case_scope_claim_stale_cancel_tags_notes_and_followups(
    integration_session, monkeypatch
) -> None:
    monkeypatch.setattr(integration_session, "commit", integration_session.flush)
    admin = User(
        email=f"admin-{uuid.uuid4().hex}@example.test",
        password_hash="unused",
        role=Role.admin,
    )
    recruiter = User(
        email=f"recruiter-{uuid.uuid4().hex}@example.test",
        password_hash="unused",
        role=Role.recruiter,
    )
    other = User(
        email=f"other-{uuid.uuid4().hex}@example.test",
        password_hash="unused",
        role=Role.recruiter,
    )
    integration_session.add_all([admin, recruiter, other])
    await integration_session.flush()
    workflow = await CaseWorkflowService(integration_session).create(_workflow(), admin.id)
    contact_service = ContactService(integration_session)
    contact = await contact_service.create(ContactCreate(display_name="Scoped"), admin)
    case_service = CaseService(integration_session)
    case = await case_service.create(
        CaseCreate(
            contact_id=contact.id,
            workflow_version_id=workflow.id,
            workflow_checksum=workflow.checksum,
            attributes={"source": "zalo"},
        ),
        admin,
    )

    assert (await case_service.get_visible(case.id, recruiter)).id == case.id
    unclaimed_version = case.version
    claimed = await case_service.assign(
        case, assignee_id=recruiter.id, version=case.version, actor=recruiter
    )
    with pytest.raises(NotFoundError):
        await case_service.get_visible(case.id, other)
    with pytest.raises(NotFoundError):
        await contact_service.get_visible(contact.id, other)
    with pytest.raises(ForbiddenError):
        await case_service.assign(
            claimed, assignee_id=other.id, version=claimed.version, actor=recruiter
        )
    with pytest.raises(ConflictError):
        await case_service.update(
            claimed,
            CaseUpdate(version=unclaimed_version, subject="stale"),
            recruiter,
        )

    assigned = await case_service.assign(
        claimed, assignee_id=other.id, version=claimed.version, actor=admin
    )
    with pytest.raises(NotFoundError):
        await case_service.add_note(assigned, body="stale viewer", actor=recruiter)
    untagged_version = assigned.version
    tagged = await case_service.replace_tags(
        assigned, tag_keys=["priority"], version=assigned.version, actor=admin
    )
    assert await case_service.tags(tagged) == ["priority"]
    with pytest.raises(ConflictError):
        await case_service.replace_tags(
            tagged, tag_keys=[], version=untagged_version, actor=admin
        )
    note = await case_service.add_note(tagged, body="append only", actor=admin)
    assert [item.id for item in await case_service.notes(tagged, limit=10)] == [note.id]
    followup = await case_service.add_followup(
        tagged,
        CaseFollowupCreate(
            due_at=datetime.now(UTC) + timedelta(days=1),
            assigned_user_id=other.id,
            note="Call",
        ),
        admin,
    )
    completed = await case_service.finish_followup(
        tagged,
        followup.id,
        version=followup.version,
        status=FollowupStatus.COMPLETED,
        actor=admin,
    )
    assert completed.status == FollowupStatus.COMPLETED.value
    with pytest.raises(ConflictError):
        await case_service.finish_followup(
            tagged,
            followup.id,
            version=followup.version,
            status=FollowupStatus.CANCELLED,
            actor=admin,
        )

    cancel_case = await case_service.create(
        CaseCreate(
            contact_id=contact.id,
            workflow_version_id=workflow.id,
            workflow_checksum=workflow.checksum,
            attributes={"source": "manual"},
        ),
        admin,
    )
    cancelled = await case_service.cancel(
        cancel_case, version=cancel_case.version, actor=admin
    )
    assert cancelled.lifecycle == "CANCELLED" and cancelled.closed_at is not None
    with pytest.raises(ConflictError):
        await case_service.transition(
            cancelled, target="done", version=cancelled.version, actor=admin
        )
    with pytest.raises(ConflictError):
        await case_service.update(
            cancelled,
            CaseUpdate(version=cancelled.version, subject="reopen"),
            admin,
        )

    invalid_user = uuid.uuid4()
    with pytest.raises(NotFoundError, match="assigned user"):
        await case_service.create(
            CaseCreate(
                contact_id=contact.id,
                workflow_version_id=workflow.id,
                workflow_checksum=workflow.checksum,
                assigned_user_id=invalid_user,
                attributes={"source": "manual"},
            ),
            admin,
        )
    with pytest.raises(NotFoundError, match="assigned user"):
        await case_service.assign(
            tagged, assignee_id=invalid_user, version=tagged.version, actor=admin
        )
    with pytest.raises(NotFoundError, match="assigned user"):
        await case_service.add_followup(
            tagged,
            CaseFollowupCreate(
                due_at=datetime.now(UTC) + timedelta(days=1),
                assigned_user_id=invalid_user,
            ),
            admin,
        )


async def test_two_sessions_converge_on_one_channel_identity(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as baseline_session:
        baseline_contacts = int(
            await baseline_session.scalar(select(func.count()).select_from(Contact)) or 0
        )

    async def resolve() -> tuple[uuid.UUID, uuid.UUID]:
        async with sessions() as session:
            identity = await ContactService(session).resolve_channel_identity(
                provider="zalo", account_key="account-a", external_id="same-user"
            )
            await session.commit()
            return identity.id, identity.contact_id

    try:
        first, second = await asyncio.gather(resolve(), resolve())
        assert first == second
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(Contact))
                == baseline_contacts + 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(ContactChannelIdentity)) == 1
            )
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.action == "resolve_contact_channel_identity",
                    AuditEvent.target_id == str(first[1]),
                )
            )
            await session.execute(
                delete(ContactChannelIdentity).where(ContactChannelIdentity.id == first[0])
            )
            await session.execute(delete(Contact).where(Contact.id == first[1]))
            await session.commit()
    finally:
        await engine.dispose()


async def test_conversation_contact_identity_ownership_constraints(
    integration_session, monkeypatch
) -> None:
    monkeypatch.setattr(integration_session, "commit", integration_session.flush)
    admin = User(
        email=f"fk-admin-{uuid.uuid4().hex}@example.test",
        password_hash="unused",
        role=Role.admin,
    )
    integration_session.add(admin)
    await integration_session.flush()
    contacts = ContactService(integration_session)
    first = await contacts.create(ContactCreate(display_name="First"), admin)
    second = await contacts.create(ContactCreate(display_name="Second"), admin)
    first_identity = await contacts.attach_identity(
        first,
        ChannelIdentityCreate(
            provider="zalo", account_key="oa.primary", external_id="first"
        ),
        admin,
    )
    second_identity = await contacts.attach_identity(
        second,
        ChannelIdentityCreate(
            provider="zalo", account_key="oa.primary", external_id="second"
        ),
        admin,
    )

    async def rejected(conversation: Conversation) -> None:
        savepoint = await integration_session.begin_nested()
        integration_session.add(conversation)
        with pytest.raises(DBAPIError):
            await integration_session.flush()
        await savepoint.rollback()

    await rejected(
        Conversation(
            zalo_chat_id=f"missing-contact-{uuid.uuid4().hex}",
            zalo_channel="oa",
            channel_identity_id=first_identity.id,
        )
    )
    await rejected(
        Conversation(
            zalo_chat_id=f"wrong-owner-{uuid.uuid4().hex}",
            zalo_channel="oa",
            contact_id=first.id,
            channel_identity_id=second_identity.id,
        )
    )
    contact_only = Conversation(
        zalo_chat_id=f"contact-only-{uuid.uuid4().hex}",
        zalo_channel="oa",
        contact_id=first.id,
    )
    integration_session.add(contact_only)
    await integration_session.flush()
    linked = Conversation(
        zalo_chat_id=f"linked-{uuid.uuid4().hex}",
        zalo_channel="oa",
        contact_id=second.id,
        channel_identity_id=second_identity.id,
    )
    integration_session.add(linked)
    await integration_session.flush()
    await rejected(
        Conversation(
            zalo_chat_id=f"duplicate-identity-{uuid.uuid4().hex}",
            zalo_channel="oa",
            contact_id=second.id,
            channel_identity_id=second_identity.id,
        )
    )
    with pytest.raises(ConflictError, match="already belongs"):
        await contacts.attach_identity(
            second,
            ChannelIdentityCreate(
                provider=first_identity.provider,
                account_key=first_identity.account_key,
                external_id=first_identity.external_id,
            ),
            admin,
        )


async def test_reassignment_is_rechecked_at_contact_and_case_mutation_time(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    workflow_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    user_ids: tuple[uuid.UUID, ...] = ()
    try:
        async with sessions() as session:
            admin = User(
                email=f"toctou-admin-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.admin,
            )
            recruiter = User(
                email=f"toctou-recruiter-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            other = User(
                email=f"toctou-other-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            session.add_all([admin, recruiter, other])
            await session.commit()
            workflow = await CaseWorkflowService(session).create(_workflow(), admin.id)
            contact = await ContactService(session).create(
                ContactCreate(display_name="Concurrent candidate"), admin
            )
            case_service = CaseService(session)
            case = await case_service.create(
                CaseCreate(
                    contact_id=contact.id,
                    workflow_version_id=workflow.id,
                    workflow_checksum=workflow.checksum,
                    attributes={"source": "zalo"},
                ),
                admin,
            )
            followup = await case_service.add_followup(
                case,
                CaseFollowupCreate(
                    due_at=datetime.now(UTC) + timedelta(days=1),
                    assigned_user_id=recruiter.id,
                ),
                admin,
            )
            workflow_id, contact_id = workflow.id, contact.id
            user_ids = (admin.id, recruiter.id, other.id)
            recruiter_id, other_id = recruiter.id, other.id
            followup_id, followup_version = followup.id, followup.version

        async with sessions() as stale_session:
            stale_recruiter = await stale_session.get(User, recruiter_id)
            assert stale_recruiter is not None
            stale_cases = CaseService(stale_session)
            stale_contacts = ContactService(stale_session)
            stale_case = await stale_cases.get_visible(case.id, stale_recruiter)
            stale_contact = await stale_contacts.get_visible(contact.id, stale_recruiter)

            async with sessions() as fresh_session:
                fresh_admin = await fresh_session.get(User, user_ids[0])
                assert fresh_admin is not None
                fresh_case = await CaseService(fresh_session).get_visible(case.id, fresh_admin)
                await CaseService(fresh_session).assign(
                    fresh_case,
                    assignee_id=other_id,
                    version=fresh_case.version,
                    actor=fresh_admin,
                )

            with pytest.raises(NotFoundError):
                await stale_contacts.update(
                    stale_contact,
                    ContactUpdate(
                        version=stale_contact.version,
                        display_name="Must not update",
                    ),
                    stale_recruiter,
                )
            with pytest.raises(NotFoundError):
                await stale_cases.add_note(
                    stale_case, body="Must not append", actor=stale_recruiter
                )
            with pytest.raises(NotFoundError):
                await stale_cases.add_followup(
                    stale_case,
                    CaseFollowupCreate(
                        due_at=datetime.now(UTC) + timedelta(days=2),
                        assigned_user_id=recruiter_id,
                    ),
                    stale_recruiter,
                )
            with pytest.raises(NotFoundError):
                await stale_cases.finish_followup(
                    stale_case,
                    followup_id,
                    version=followup_version,
                    status=FollowupStatus.COMPLETED,
                    actor=stale_recruiter,
                )
    finally:
        if workflow_id is not None and contact_id is not None and user_ids:
            await _cleanup_committed_case_kernel(
                engine,
                workflow_id=workflow_id,
                user_ids=user_ids,
                contact_ids=(contact_id,),
            )
        await engine.dispose()


async def test_recruiter_case_create_locks_current_contact_visibility_anchor(
    integration_database: IntegrationDatabase, monkeypatch
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    workflow_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    user_ids: tuple[uuid.UUID, ...] = ()
    try:
        async with sessions() as setup:
            admin = User(
                email=f"create-race-admin-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.admin,
            )
            recruiter = User(
                email=f"create-race-recruiter-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            other = User(
                email=f"create-race-other-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            setup.add_all([admin, recruiter, other])
            await setup.commit()
            workflow = await CaseWorkflowService(setup).create(_workflow(), admin.id)
            contact = await ContactService(setup).create(
                ContactCreate(display_name="Create race candidate"), admin
            )
            anchor = await CaseService(setup).create(
                CaseCreate(
                    contact_id=contact.id,
                    workflow_version_id=workflow.id,
                    workflow_checksum=workflow.checksum,
                    attributes={"source": "anchor"},
                ),
                admin,
            )
            workflow_id, contact_id = workflow.id, contact.id
            user_ids = (admin.id, recruiter.id, other.id)
            recruiter_id, other_id = recruiter.id, other.id
            workflow_checksum = workflow.checksum
            anchor_id = anchor.id

        async with sessions() as locker:
            lock_recruiter = await locker.get(User, recruiter_id)
            assert lock_recruiter is not None
            await ContactService(locker).lock_visible_anchor(contact_id, lock_recruiter)
            async with sessions() as competing_assignment:
                await competing_assignment.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await competing_assignment.execute(
                        update(Case)
                        .where(Case.id == anchor_id)
                        .values(assigned_user_id=other_id)
                    )
                await competing_assignment.rollback()
            await locker.rollback()

        visible_read = asyncio.Event()
        resume_create = asyncio.Event()
        original_get_visible = ContactService.get_visible

        async def pause_after_visible_read(self, selected_contact_id, viewer):
            result = await original_get_visible(self, selected_contact_id, viewer)
            if viewer.id == recruiter_id and selected_contact_id == contact_id:
                visible_read.set()
                await resume_create.wait()
            return result

        monkeypatch.setattr(ContactService, "get_visible", pause_after_visible_read)

        async with sessions() as stale_session:
            stale_recruiter = await stale_session.get(User, recruiter_id)
            assert stale_recruiter is not None
            create_task = asyncio.create_task(
                CaseService(stale_session).create(
                    CaseCreate(
                        contact_id=contact_id,
                        workflow_version_id=workflow_id,
                        workflow_checksum=workflow_checksum,
                        attributes={"source": "stale"},
                    ),
                    stale_recruiter,
                )
            )
            await asyncio.wait_for(visible_read.wait(), timeout=5)

            async with sessions() as admin_session:
                fresh_admin = await admin_session.get(User, user_ids[0])
                assert fresh_admin is not None
                fresh_anchor = await CaseService(admin_session).get_visible(
                    anchor_id, fresh_admin
                )
                await CaseService(admin_session).assign(
                    fresh_anchor,
                    assignee_id=other_id,
                    version=fresh_anchor.version,
                    actor=fresh_admin,
                )

            resume_create.set()
            with pytest.raises(NotFoundError, match="contact not found"):
                await create_task
            await stale_session.rollback()

        async with sessions() as verify:
            assert (
                await verify.scalar(
                    select(func.count()).select_from(Case).where(Case.contact_id == contact_id)
                )
                == 1
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.action == "create_case",
                        AuditEvent.actor_id == recruiter_id,
                    )
                )
                == 0
            )
    finally:
        if workflow_id is not None and contact_id is not None and user_ids:
            await _cleanup_committed_case_kernel(
                engine,
                workflow_id=workflow_id,
                user_ids=user_ids,
                contact_ids=(contact_id,),
            )
        await engine.dispose()


async def test_recruiter_case_create_guards_conversation_only_visibility(
    integration_database: IntegrationDatabase, monkeypatch
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    workflow_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    user_ids: tuple[uuid.UUID, ...] = ()
    try:
        async with sessions() as setup:
            admin = User(
                email=f"conversation-anchor-admin-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.admin,
            )
            recruiter = User(
                email=f"conversation-anchor-recruiter-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            other = User(
                email=f"conversation-anchor-other-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            setup.add_all([admin, recruiter, other])
            await setup.commit()
            workflow = await CaseWorkflowService(setup).create(_workflow(), admin.id)
            contact = await ContactService(setup).create(
                ContactCreate(display_name="Conversation-only candidate"), admin
            )
            conversation = Conversation(
                zalo_chat_id=f"oa:{uuid.uuid4().hex}",
                zalo_channel="oa",
                contact_id=contact.id,
            )
            setup.add(conversation)
            await setup.commit()
            workflow_id, contact_id, conversation_id = (
                workflow.id,
                contact.id,
                conversation.id,
            )
            user_ids = (admin.id, recruiter.id, other.id)
            recruiter_id, other_id = recruiter.id, other.id
            workflow_checksum = workflow.checksum

        async with sessions() as locker:
            lock_recruiter = await locker.get(User, recruiter_id)
            assert lock_recruiter is not None
            await ContactService(locker).lock_visible_anchor(contact_id, lock_recruiter)
            async with sessions() as competing_assignment:
                await competing_assignment.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await competing_assignment.execute(
                        update(Conversation)
                        .where(Conversation.id == conversation_id)
                        .values(assigned_recruiter_id=other_id)
                    )
                await competing_assignment.rollback()
            await locker.rollback()

        visible_read = asyncio.Event()
        resume_create = asyncio.Event()
        original_get_visible = ContactService.get_visible

        async def pause_after_visible_read(self, selected_contact_id, viewer):
            result = await original_get_visible(self, selected_contact_id, viewer)
            if viewer.id == recruiter_id and selected_contact_id == contact_id:
                visible_read.set()
                await resume_create.wait()
            return result

        monkeypatch.setattr(ContactService, "get_visible", pause_after_visible_read)

        async with sessions() as stale_session:
            stale_recruiter = await stale_session.get(User, recruiter_id)
            assert stale_recruiter is not None
            create_task = asyncio.create_task(
                CaseService(stale_session).create(
                    CaseCreate(
                        contact_id=contact_id,
                        workflow_version_id=workflow_id,
                        workflow_checksum=workflow_checksum,
                        attributes={"source": "stale-conversation"},
                    ),
                    stale_recruiter,
                )
            )
            await asyncio.wait_for(visible_read.wait(), timeout=5)

            async with sessions() as admin_session:
                await admin_session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(assigned_recruiter_id=other_id)
                )
                await admin_session.commit()

            resume_create.set()
            with pytest.raises(NotFoundError, match="contact not found"):
                await create_task
            await stale_session.rollback()

        async with sessions() as verify:
            assert (
                await verify.scalar(
                    select(func.count()).select_from(Case).where(Case.contact_id == contact_id)
                )
                == 0
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.action == "create_case",
                        AuditEvent.actor_id == recruiter_id,
                    )
                )
                == 0
            )
    finally:
        if (
            workflow_id is not None
            and contact_id is not None
            and conversation_id is not None
            and user_ids
        ):
            await _cleanup_committed_case_kernel(
                engine,
                workflow_id=workflow_id,
                user_ids=user_ids,
                contact_ids=(contact_id,),
                conversation_ids=(conversation_id,),
            )
        await engine.dispose()


async def test_assignee_existence_lock_closes_delete_race(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id: uuid.UUID | None = None
    try:
        async with sessions() as setup:
            user = User(
                email=f"lock-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.recruiter,
            )
            setup.add(user)
            await setup.commit()
            user_id = user.id

        async with sessions() as locker:
            await CaseService(locker)._ensure_user(user_id)
            async with sessions() as deleter:
                await deleter.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await deleter.execute(delete(User).where(User.id == user_id))
                await deleter.rollback()
            await locker.rollback()
    finally:
        if user_id is not None:
            async with engine.begin() as connection:
                await connection.execute(delete(User).where(User.id == user_id))
        await engine.dispose()


async def test_published_workflow_rejects_parent_child_update_delete_and_insert(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id: uuid.UUID | None = None
    workflow_id: uuid.UUID | None = None
    try:
        async with sessions() as session:
            actor = User(
                email=f"immutable-{uuid.uuid4().hex}@example.test",
                password_hash="unused",
                role=Role.admin,
            )
            session.add(actor)
            await session.flush()
            workflow = await CaseWorkflowService(session).create(_workflow(), actor.id)
            actor_id, workflow_id = actor.id, workflow.id

        statements = (
            update(CaseWorkflowVersion)
            .where(CaseWorkflowVersion.id == workflow_id)
            .values(label="Changed"),
            update(CaseWorkflowStage)
            .where(
                CaseWorkflowStage.workflow_version_id == workflow_id,
                CaseWorkflowStage.stage_key == "new",
            )
            .values(label="Changed"),
            delete(CaseWorkflowStage).where(
                CaseWorkflowStage.workflow_version_id == workflow_id,
                CaseWorkflowStage.stage_key == "new",
            ),
            delete(CaseWorkflowVersion).where(CaseWorkflowVersion.id == workflow_id),
        )
        for statement in statements:
            async with sessions() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(statement)
                await session.rollback()

        late_rows = (
            CaseWorkflowStage(
                workflow_version_id=workflow_id,
                stage_key="late",
                label="Late",
                position=2,
                is_initial=False,
                is_terminal=True,
            ),
            CaseWorkflowTransition(
                workflow_version_id=workflow_id,
                from_stage_key="done",
                to_stage_key="new",
            ),
            CaseTagDefinition(
                workflow_version_id=workflow_id,
                tag_key="late",
                label="Late",
                tone="neutral",
                position=2,
            ),
        )
        for row in late_rows:
            async with sessions() as session:
                session.add(row)
                with pytest.raises(DBAPIError, match="published immutable workflow"):
                    await session.flush()
                await session.rollback()
    finally:
        if workflow_id is not None and actor_id is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "ALTER TABLE case_workflow_versions DISABLE TRIGGER "
                        "case_workflow_versions_immutable"
                    )
                )
                for table, trigger in (
                    ("case_workflow_transitions", "case_workflow_transitions_immutable"),
                    ("case_tag_definitions", "case_tag_definitions_immutable"),
                    ("case_workflow_stages", "case_workflow_stages_immutable"),
                ):
                    await connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
                await connection.execute(
                    delete(AuditEvent).where(AuditEvent.target_id == str(workflow_id))
                )
                await connection.execute(
                    delete(CaseWorkflowTransition).where(
                        CaseWorkflowTransition.workflow_version_id == workflow_id
                    )
                )
                await connection.execute(
                    delete(CaseTagDefinition).where(
                        CaseTagDefinition.workflow_version_id == workflow_id
                    )
                )
                await connection.execute(
                    delete(CaseWorkflowStage).where(
                        CaseWorkflowStage.workflow_version_id == workflow_id
                    )
                )
                await connection.execute(
                    delete(CaseWorkflowVersion).where(CaseWorkflowVersion.id == workflow_id)
                )
                await connection.execute(delete(User).where(User.id == actor_id))
                await connection.execute(
                    text(
                        "ALTER TABLE case_workflow_versions ENABLE TRIGGER "
                        "case_workflow_versions_immutable"
                    )
                )
                for table, trigger in (
                    ("case_workflow_transitions", "case_workflow_transitions_immutable"),
                    ("case_tag_definitions", "case_tag_definitions_immutable"),
                    ("case_workflow_stages", "case_workflow_stages_immutable"),
                ):
                    await connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
        await engine.dispose()
