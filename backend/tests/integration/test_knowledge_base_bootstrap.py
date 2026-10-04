"""Database proof for the generic legacy KB/Project bootstrap."""

from __future__ import annotations

import uuid

import pytest

from app.models.company import Project
from app.models.knowledge import KnowledgeBaseMode
from app.models.user import Role, User
from app.schemas.knowledge_bases import LegacyKnowledgeBootstrap
from app.services.knowledge.base_service import KnowledgeBaseService


pytestmark = pytest.mark.integration


async def test_legacy_bootstrap_creates_rag_kb_and_connects_project(
    integration_session,
) -> None:
    """The bootstrap wires projects to a KB and is idempotent on repeat.

    It used to also attach a ``Persona`` and rename it. Personas were removed on
    2026-10-04, so the Agent half of the legacy shape is gone and this now proves
    the KB/Project half plus the idempotency that made re-running it safe.
    """
    actor = User(
        email=f"kb-bootstrap-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    legacy_project = Project(
        name="Legacy factory",
        slug=f"legacy-factory-{uuid.uuid4().hex}",
    )
    integration_session.add_all([actor, legacy_project])
    await integration_session.flush()

    knowledge_base = await KnowledgeBaseService(integration_session).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            knowledge_base_name="Production knowledge",
            knowledge_base_slug=f"production-knowledge-{uuid.uuid4().hex}",
            project_ids=[legacy_project.id],
        ),
        actor,
    )

    await integration_session.refresh(legacy_project)
    assert knowledge_base.mode is KnowledgeBaseMode.RAG
    assert legacy_project.knowledge_base_id == knowledge_base.id

    repeated = await KnowledgeBaseService(integration_session).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            knowledge_base_name="Production knowledge",
            knowledge_base_slug=knowledge_base.slug,
            project_ids=[legacy_project.id],
        ),
        actor,
    )
    assert repeated.id == knowledge_base.id
