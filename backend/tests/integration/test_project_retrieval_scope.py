"""Real vector retrieval proof for category coverage and live project authority."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import cast, literal
from sqlalchemy.types import UserDefinedType

from app.graph.tools.knowledge import search_knowledge
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.project_knowledge.domain.category_catalog import CATEGORY_DEFINITIONS
from app.services.retrieval.document_repository import DocumentRepository
from app.services.retrieval.repository import RetrievalRepository

pytestmark = pytest.mark.integration
_VECTOR = "[" + ",".join(["0.1"] * 3072) + "]"


class _Vector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kwargs):
        return "vector"


async def _project(db, name: str, *, active: bool = True) -> Project:
    project = Project(
        name=name, slug=f"retrieval-{uuid.uuid4().hex}", is_active=active,
        category_authority_started=True,
    )
    db.add(project)
    await db.flush()
    base = KnowledgeBase(
        name=name, slug=f"kb-{uuid.uuid4().hex}", mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
    )
    db.add(base)
    await db.flush()
    project.knowledge_base_id = base.id
    await db.flush()
    return project


async def _evidence(db, project: Project, category_key: str, *, category=None, content=None):
    if category is None:
        category = KnowledgeCategory(project_id=project.id, category_key=category_key)
        db.add(category)
        await db.flush()
        revision_no = 1
    else:
        revision_no = 2
    revision = KnowledgeCategoryRevision(
        category_id=category.id, revision_no=revision_no,
        status=KnowledgeCategoryRevisionStatus.ACTIVE,
        source_filename=f"{category_key}.md", source_markdown="published evidence",
        normalized_payload={"category": category_key}, content_sha256="a" * 64,
    )
    db.add(revision)
    await db.flush()
    category.active_revision_id = revision.id
    document = KnowledgeDocument(
        project_id=project.id, file_name=f"{category_key}.md",
        source="category_markdown", status=KnowledgeStatus.PUBLISHED,
        category_revision_id=revision.id,
    )
    db.add(document)
    await db.flush()
    body = content or f"{project.name}: published {category_key} evidence"
    chunk = KnowledgeChunk(
        project_id=project.id, document_id=document.id, category_revision_id=revision.id,
        chunk_type="category_record", category=category_key, content=body,
        source_quote=body, metadata_={"category": category_key}, token_count=10,
        embedding=cast(literal(_VECTOR), _Vector()),
    )
    db.add(chunk)
    await db.flush()
    return category, chunk


@pytest.mark.parametrize("ann", [False, True])
async def test_retrieval_covers_every_category_without_old_or_cross_project_evidence(
    integration_session, monkeypatch, ann,
):
    db = integration_session
    monkeypatch.setattr(DocumentRepository, "_ann_enabled", staticmethod(lambda: ann))
    project = await _project(db, "Selected factory")
    other = await _project(db, "Other factory")
    inactive = await _project(db, "Inactive factory", active=False)
    for definition in CATEGORY_DEFINITIONS:
        await _evidence(db, project, definition.key.value)
    category, old = await _evidence(db, other, "faq", content="OLD published FAQ")
    await _evidence(db, other, "faq", category=category, content="NEW published FAQ")
    await _evidence(db, inactive, "faq")
    await db.flush()

    scoped = RetrievalRepository(db, page_project_ids=(str(project.id),))
    rows = await scoped.match_documents(_VECTOR, 25, "{}")
    assert len(rows) == len(CATEGORY_DEFINITIONS) == 12
    assert {row.category for row in rows} == {definition.key.value for definition in CATEGORY_DEFINITIONS}
    assert {row.project_slug for row in rows} == {project.slug}
    assert {row.project_name for row in rows} == {project.name}
    assert all(row.source_file == f"{row.category}.md" for row in rows)
    assert await scoped.match_documents(_VECTOR, 25, "{}", project_ids=[]) == []
    assert await scoped.match_documents(_VECTOR, 25, "{}", project_ids=[str(other.id)]) == []
    faq = await scoped.match_faq(_VECTOR)
    assert len(faq) == 1 and faq[0].project_name == project.name
    assert await scoped.match_faq(_VECTOR, project_ids=[]) == []
    assert await scoped.match_faq(_VECTOR, project_ids=[str(other.id)]) == []

    global_repo = RetrievalRepository(db)
    global_rows = await global_repo.match_documents(_VECTOR, 25, "{}")
    assert len(global_rows) == 13
    assert str(old.id) not in {str(row.id) for row in global_rows}
    assert all(row.project_name != inactive.name for row in global_rows)
    assert {row.content for row in await global_repo.match_faq(_VECTOR)} == {
        f"{project.name}: published faq evidence", "NEW published FAQ",
    }


async def test_page_catalog_and_search_recheck_deactivated_or_detached_projects(integration_session):
    db = integration_session
    project = await _project(db, "Assigned factory")
    await _evidence(db, project, "faq")
    repo = RetrievalRepository(db, page_project_ids=(str(project.id),))
    assert await repo.active_project_ids() == [str(project.id)]

    project.is_active = False
    await db.flush()
    assert await repo.active_project_ids() == []
    assert await repo.match_documents(_VECTOR, 10, "{}") == []
    assert await repo.match_faq(_VECTOR) == []

    async def unused_embedder(_query):
        raise AssertionError("an empty active scope must stop before embedding or cached evidence")

    assert "Không tìm thấy" in await search_knowledge(repo, unused_embedder, "thu nhập")
    project.is_active = True
    project.knowledge_base_id = None
    await db.flush()
    assert await repo.active_project_ids() == []
    assert await repo.match_documents(_VECTOR, 10, "{}") == []
    assert await repo.match_faq(_VECTOR) == []
    assert "Không tìm thấy" in await search_knowledge(repo, unused_embedder, "thu nhập")


@pytest.mark.parametrize("corruption", ["revision_owner", "chunk_owner"])
async def test_retrieval_excludes_inconsistent_project_evidence_ownership(
    integration_session, corruption,
):
    db = integration_session
    project = await _project(db, "Selected factory")
    other = await _project(db, "Other factory")
    category, own_chunk = await _evidence(db, project, "faq")
    _other_category, other_chunk = await _evidence(db, other, "faq")
    if corruption == "revision_owner":
        category.active_revision_id = other_chunk.category_revision_id
        document = await db.get(KnowledgeDocument, other_chunk.document_id)
        document.project_id = project.id
        other_chunk.project_id = project.id
    else:
        own_chunk.project_id = other.id
    await db.flush()
    repo = RetrievalRepository(db, page_project_ids=(str(project.id),))
    assert await repo.match_documents(_VECTOR, 10, "{}") == []
    assert await repo.match_faq(_VECTOR) == []
