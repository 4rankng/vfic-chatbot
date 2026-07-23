"""Persona edits append immutable content versions for installation pinning."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.persona import PersonaVersion
from app.models.knowledge import KnowledgeBase, KnowledgeBaseMode
from app.models.user import Role, User
from app.schemas.personas import PersonaCreate, PersonaUpdate
from app.shared.domain.errors import ConflictError
from app.services.personas import PersonaService

pytestmark = pytest.mark.integration


async def test_persona_content_edits_append_versions_and_database_rejects_mutation(
    integration_session,
):
    actor = User(
        email=f"persona-version-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    integration_session.add(actor)
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Test RAG knowledge",
        slug=f"test-rag-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    service = PersonaService(integration_session)

    persona = await service.create(
        PersonaCreate(
            name="Customer voice",
            body_md="Version one",
            knowledge_base_id=knowledge_base.id,
        ),
        actor,
    )
    await service.update(persona.id, PersonaUpdate(body_md="Version two"), actor)

    versions = list(
        (
            await integration_session.scalars(
                select(PersonaVersion)
                .where(PersonaVersion.persona_id == persona.id)
                .order_by(PersonaVersion.version_no)
            )
        ).all()
    )
    assert [(version.version_no, version.body_md) for version in versions] == [
        (1, "Version one"),
        (2, "Version two"),
    ]
    assert versions[0].checksum != versions[1].checksum

    with pytest.raises(ConflictError, match="immutable versions"):
        await service.delete(persona.id)

    with pytest.raises(DBAPIError, match="append-only"):
        async with integration_session.begin_nested():
            versions[0].body_md = "mutated"
            await integration_session.flush()

    integration_session.expire(versions[0])
    await integration_session.refresh(versions[0])
    assert versions[0].body_md == "Version one"

    persona_id = persona.id
    await integration_session.delete(actor)
    await integration_session.flush()
    integration_session.expire_all()
    remaining_versions = list(
        (
            await integration_session.scalars(
                select(PersonaVersion).where(PersonaVersion.persona_id == persona_id)
            )
        ).all()
    )
    assert remaining_versions
    assert all(version.created_by is None for version in remaining_versions)
