"""Real database proof of Page scope and cached KB availability checks."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from app.graph import adapters
from app.models.company import Project
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode

pytestmark = pytest.mark.integration


async def _direct_project(db, name):
    project = Project(id=uuid.uuid4(), name=name, slug=f"scope-{uuid.uuid4().hex}", is_active=True)
    db.add(project)
    await db.flush()
    kb = KnowledgeBase(
        id=uuid.uuid4(), project_id=project.id, name=name,
        slug=f"scope-kb-{uuid.uuid4().hex}", mode=KnowledgeBaseMode.DIRECT_CONTEXT,
    )
    db.add(kb)
    await db.flush()
    project.knowledge_base_id = kb.id
    content = f"Kiến thức riêng của {name}."
    db.add(KnowledgeBaseDirectFile(
        knowledge_base_id=kb.id, filename="brief.txt", raw_text=content,
        normalized_text=content, content_sha256="1" * 64,
        char_count=len(content), line_count=1,
    ))
    await db.flush()
    return project, kb, adapters._DirectContextCatalogEntry(
        project_id=project.id, slug=project.slug, name=project.name,
        aliases=(), kb_id=kb.id, mode="DIRECT_CONTEXT",
    )


async def test_direct_knowledge_respects_page_scope_even_with_global_warm_catalog(
    integration_session, monkeypatch,
):
    public, _public_kb, public_entry = await _direct_project(integration_session, "Public Project")
    private, _private_kb, private_entry = await _direct_project(integration_session, "Private Project")
    monkeypatch.setattr(
        adapters, "_load_direct_context_catalog",
        AsyncMock(return_value=[public_entry, private_entry]),
    )
    monkeypatch.setattr(
        "app.services.personas.repository.PersonaRepository.active_persona_body",
        AsyncMock(return_value="Persona"),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_capacity.ensure_direct_context_fits", AsyncMock(),
    )
    router = adapters._DirectContextAdapter(
        integration_session, page_project_ids=(str(public.id),),
    )
    conversation = SimpleNamespace(focused_project_id=private.id, project_context_state="FOCUSED")

    denied = await router.resolve(conversation, "Private Project lương bao nhiêu?")
    allowed = await router.resolve(conversation, "Public Project lương bao nhiêu?")

    assert denied.state == "EXPLORE"
    assert denied.direct_context is None
    assert allowed.project_id == str(public.id)
    assert allowed.direct_context.knowledge_text == "Kiến thức riêng của Public Project."


@pytest.mark.parametrize("change", ["deactivate", "switch_to_rag"])
async def test_warm_routing_cannot_serve_inactive_or_superseded_direct_knowledge(
    integration_session, monkeypatch, change,
):
    project, kb, cached = await _direct_project(integration_session, "Changing Project")
    monkeypatch.setattr(adapters, "_load_direct_context_catalog", AsyncMock(return_value=[cached]))
    if change == "deactivate":
        await integration_session.execute(
            update(Project).where(Project.id == project.id).values(is_active=False)
            .execution_options(synchronize_session=False)
        )
    else:
        await integration_session.execute(
            update(KnowledgeBase).where(KnowledgeBase.id == kb.id).values(mode=KnowledgeBaseMode.RAG)
            .execution_options(synchronize_session=False)
        )
    # The same session still has the old ORM objects; both the Redis routing
    # hint and its identity map must yield to the current database projection.
    conversation = SimpleNamespace(focused_project_id=project.id, project_context_state="FOCUSED")
    result = await adapters._DirectContextAdapter(integration_session).resolve(
        conversation, "Changing Project có xe đưa đón không?",
    )

    assert result.direct_context is None
    if change == "deactivate":
        assert result.state == "EXPLORE"
        assert conversation.focused_project_id is None
    else:
        assert result.state == "FOCUSED"
        assert result.knowledge_mode == "RAG"
