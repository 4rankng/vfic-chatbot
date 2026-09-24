"""Database proof for the generic legacy Agent/KB/Project bootstrap."""

from __future__ import annotations

import uuid

import pytest

from app.models.company import Project
from app.models.knowledge import KnowledgeBaseMode
from app.models.persona import Persona, default_persona_followup_rules
from app.models.user import Role, User
from app.schemas.knowledge_bases import LegacyKnowledgeBootstrap
from app.services.knowledge.base_service import KnowledgeBaseService


pytestmark = pytest.mark.integration


async def test_legacy_bootstrap_creates_rag_kb_and_connects_agent_and_project(
    integration_session,
) -> None:
    actor = User(
        email=f"kb-bootstrap-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    legacy_persona = Persona(
        name="Legacy agent",
        slug=f"legacy-agent-{uuid.uuid4().hex}",
        body_md="Legacy body",
        followup_rules=default_persona_followup_rules(),
        created_by=actor.id,
    )
    legacy_project = Project(
        name="Legacy factory",
        slug=f"legacy-factory-{uuid.uuid4().hex}",
    )
    integration_session.add_all([actor, legacy_persona, legacy_project])
    await integration_session.flush()

    knowledge_base = await KnowledgeBaseService(integration_session).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            persona_id=legacy_persona.id,
            knowledge_base_name="Production knowledge",
            knowledge_base_slug=f"production-knowledge-{uuid.uuid4().hex}",
            project_ids=[legacy_project.id],
            persona_name="Default",
            persona_slug=f"default-{uuid.uuid4().hex}",
        ),
        actor,
    )

    await integration_session.refresh(legacy_persona)
    await integration_session.refresh(legacy_project)
    assert knowledge_base.mode is KnowledgeBaseMode.RAG
    assert legacy_persona.knowledge_base_id == knowledge_base.id
    assert legacy_project.knowledge_base_id == knowledge_base.id
    assert legacy_persona.name == "Default"

    repeated = await KnowledgeBaseService(integration_session).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            persona_id=legacy_persona.id,
            knowledge_base_name="Production knowledge",
            knowledge_base_slug=knowledge_base.slug,
            project_ids=[legacy_project.id],
            persona_name="Default",
            persona_slug=legacy_persona.slug,
        ),
        actor,
    )
    assert repeated.id == knowledge_base.id
