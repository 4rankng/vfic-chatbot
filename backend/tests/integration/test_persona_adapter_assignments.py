"""Integration coverage for adapter-scoped persona assignment behavior."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.knowledge import KnowledgeBase, KnowledgeBaseMode
from app.models.persona import (
    AdapterPersonaAssignment,
    Persona,
    default_persona_followup_rules,
)
from app.models.user import Role, User
from app.schemas.personas import PersonaAssignmentUpdate
from app.shared.domain.errors import ConflictError
from app.services.personas import PersonaService, persona_out_from_model
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


async def _admin(integration_session) -> User:
    admin = User(
        email=f"persona-admin-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    integration_session.add(admin)
    await integration_session.flush()
    return admin


def _persona(*, admin: User, kb: KnowledgeBase, name: str) -> Persona:
    return Persona(
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        knowledge_base_id=kb.id,
        body_md=f"{name} body",
        followup_rules=default_persona_followup_rules(),
        created_by=admin.id,
    )


async def test_adapter_assignment_set_clear_and_effective_provider_scope(integration_session) -> None:
    admin = await _admin(integration_session)
    kb_default = KnowledgeBase(
        name="Default KB",
        slug=f"default-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        created_by=admin.id,
    )
    kb_override = KnowledgeBase(
        name="Override KB",
        slug=f"override-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        created_by=admin.id,
    )
    integration_session.add_all([kb_default, kb_override])
    await integration_session.flush()

    default_persona = _persona(admin=admin, kb=kb_default, name="Default Persona")
    override_persona = _persona(admin=admin, kb=kb_override, name="Override Persona")
    integration_session.add_all([default_persona, override_persona])
    await integration_session.flush()

    service = PersonaService(integration_session)
    await service.activate(default_persona.id)

    assigned = await service.update_adapter_assignment(
        "zalo_oa",
        PersonaAssignmentUpdate(persona_id=override_persona.id),
        admin,
    )
    assert assigned.provider == "zalo_oa"
    assert assigned.persona_id == override_persona.id
    assert assigned.effective_persona_id == override_persona.id
    assert assigned.is_default is False

    listed = {row.provider: row for row in await service.list_adapter_assignments()}
    assert listed["zalo_bot"].effective_persona_id == default_persona.id
    assert listed["zalo_bot"].is_default is True
    assert listed["facebook_messenger"].effective_persona_id == default_persona.id
    assert listed["zalo_oa"].effective_persona_id == override_persona.id

    default_out = persona_out_from_model(await service.get(default_persona.id))
    override_out = persona_out_from_model(await service.get(override_persona.id))
    assert default_out.effective_adapter_providers == ["zalo_bot", "facebook_messenger"]
    assert override_out.effective_adapter_providers == ["zalo_oa"]

    cleared = await service.update_adapter_assignment(
        "zalo_oa",
        PersonaAssignmentUpdate(persona_id=None),
        admin,
    )
    assert cleared.provider == "zalo_oa"
    assert cleared.persona_id is None
    assert cleared.effective_persona_id == default_persona.id
    assert cleared.is_default is True


async def test_adapter_assignment_rejects_unsupported_provider(integration_session) -> None:
    admin = await _admin(integration_session)

    with pytest.raises(ValueError, match="Unsupported adapter provider"):
        await PersonaService(integration_session).update_adapter_assignment(
            "telegram",
            PersonaAssignmentUpdate(persona_id=None),
            admin,
        )


async def test_adapter_assignment_requires_persona_readiness(integration_session) -> None:
    admin = await _admin(integration_session)
    direct_kb = KnowledgeBase(
        name="Direct KB",
        slug=f"direct-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        created_by=admin.id,
    )
    integration_session.add(direct_kb)
    await integration_session.flush()
    direct_persona = _persona(admin=admin, kb=direct_kb, name="Direct Persona")
    integration_session.add(direct_persona)
    await integration_session.flush()

    with pytest.raises(
        ConflictError,
        match="A direct-context knowledge base needs one text file before use",
    ):
        await PersonaService(integration_session).update_adapter_assignment(
            "zalo_bot",
            PersonaAssignmentUpdate(persona_id=direct_persona.id),
            admin,
        )


async def test_concurrent_first_assignments_are_atomic(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    admin_id: uuid.UUID | None = None
    knowledge_base_id: uuid.UUID | None = None
    persona_ids: tuple[uuid.UUID, uuid.UUID] | None = None
    try:
        async with sessions() as seed:
            admin = User(
                email=f"persona-race-{uuid.uuid4().hex}@example.test",
                password_hash="not-used",
                role=Role.admin,
            )
            kb = KnowledgeBase(
                name="Race KB",
                slug=f"race-kb-{uuid.uuid4().hex}",
                mode=KnowledgeBaseMode.RAG,
                created_by=admin.id,
            )
            seed.add_all([admin, kb])
            await seed.flush()
            first = _persona(admin=admin, kb=kb, name="Race First")
            second = _persona(admin=admin, kb=kb, name="Race Second")
            seed.add_all([first, second])
            await seed.commit()
            admin_id = admin.id
            knowledge_base_id = kb.id
            persona_ids = (first.id, second.id)

        async def assign(persona_id: uuid.UUID):
            async with sessions() as session:
                admin = await session.get(User, admin_id)
                assert admin is not None
                return await PersonaService(session).update_adapter_assignment(
                    "facebook_messenger",
                    PersonaAssignmentUpdate(persona_id=persona_id),
                    admin,
                )

        results = await asyncio.gather(*(assign(persona_id) for persona_id in persona_ids))
        assert {result.provider for result in results} == {"facebook_messenger"}

        async with sessions() as verification:
            assignment = await verification.get(
                AdapterPersonaAssignment,
                "facebook_messenger",
            )
            assert assignment is not None
            assert assignment.persona_id in persona_ids
    finally:
        if admin_id is not None and knowledge_base_id is not None and persona_ids is not None:
            async with sessions() as cleanup:
                await cleanup.execute(
                    delete(AdapterPersonaAssignment).where(
                        AdapterPersonaAssignment.provider == "facebook_messenger"
                    )
                )
                await cleanup.execute(delete(Persona).where(Persona.id.in_(persona_ids)))
                await cleanup.execute(
                    delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
                )
                await cleanup.execute(delete(User).where(User.id == admin_id))
                await cleanup.commit()
        await engine.dispose()
