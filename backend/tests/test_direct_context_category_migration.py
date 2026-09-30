"""Unit-lane proof for staging a legacy DIRECT_CONTEXT project onto the catalog.

Companion to ``tests/integration/test_direct_context_category_migration.py``,
which proves the cutover itself against a real database (authority flag, card
replacement, knowledge-base mode flip and the rollback restore). This file runs
the chain mechanics on the brief chain's fake session: the stage gate that now
admits any knowledge mode, the category-row seeding a DIRECT_CONTEXT project
needs before its first write, the queue receipt, and the projection deferral
that keeps the legacy card protected until the cutover.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.company import Project
from app.models.knowledge import KnowledgeBase, KnowledgeBaseMode
from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevisionStatus,
)
from app.project_knowledge.application.jobs import (
    ProjectKnowledgeJobRequest,
    ProjectKnowledgeJobs,
)
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.shared.domain.errors import ConflictError, NotFoundError
from tests.test_brief_fixture_ingestion import (
    _FakeSession,
    _UnitEmbedder,
    _jobs_yaml,
)


class _RecordingJobPort:
    """Staging must hand the revision to the queue and keep its receipt."""

    def __init__(self) -> None:
        self.requests: list[ProjectKnowledgeJobRequest] = []

    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str:
        self.requests.append(request)
        return f"job-{len(self.requests)}"


async def _seed_direct_context_project(
    session: _FakeSession,
) -> tuple[Project, SimpleNamespace]:
    actor = SimpleNamespace(id=uuid.uuid4())
    project = Project(
        slug="rorze",
        name="Rorze",
        is_active=True,
        category_authority_started=False,
        summary="Legacy single-page summary",
        index_card={
            "summary": "Legacy single-page summary",
            "highlights": ["Có xe đưa đón"],
        },
    )
    session.add(project)
    await session.flush()
    knowledge_base = KnowledgeBase(
        name="Rorze Knowledge",
        slug="rorze-kb",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        project_id=project.id,
        created_by=actor.id,
    )
    session.add(knowledge_base)
    await session.flush()
    project.knowledge_base_id = knowledge_base.id
    return project, actor


def _migration_service(session: _FakeSession) -> tuple[KnowledgeCategoryService, _RecordingJobPort]:
    job_port = _RecordingJobPort()
    service = KnowledgeCategoryService(
        session,
        jobs=ProjectKnowledgeJobs(job_port),
        enforce_retrieval_selftest=False,
    )
    return service, job_port


async def test_stage_admits_direct_context_project_and_seeds_rows(monkeypatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    project, actor = await _seed_direct_context_project(session)
    service, job_port = _migration_service(session)

    # The catalog poll reads before any write: twelve empty categories, and the
    # project owns no category rows at all yet.
    catalog = await service.list_catalog(project.id)
    assert len(catalog) == 12
    assert all(item.active_revision_id is None for item in catalog)
    assert not [row for row in session.added if isinstance(row, KnowledgeCategory)]

    revision, job_id = await service.stage_replacement(
        project_id=project.id,
        category_key=KnowledgeCategoryKey.JOBS,
        filename="jobs.yaml",
        source_yaml=_jobs_yaml(),
        actor=actor,
    )

    assert job_id == "job-1"
    assert [request.aggregate_id for request in job_port.requests] == [revision.id]
    assert revision.status is KnowledgeCategoryRevisionStatus.STAGED
    # Seeding rides the first stage: every category row now exists, which is
    # what makes the later explicit clears and the cutover readiness check
    # satisfiable for a project that started with none.
    assert len([row for row in session.added if isinstance(row, KnowledgeCategory)]) == 12

    # A missing project stays a 404 — the relaxed mode gate does not widen that.
    with pytest.raises(NotFoundError):
        await service.stage_replacement(
            project_id=uuid.uuid4(),
            category_key=KnowledgeCategoryKey.JOBS,
            filename="jobs.yaml",
            source_yaml=_jobs_yaml(),
            actor=actor,
        )


async def test_active_source_stays_rag_only_while_staging_admits_any_mode(monkeypatch) -> None:
    """The gate relaxes for writes and the catalog poll, not for reading a
    category's active source — that read still belongs to the RAG panel."""
    session = _FakeSession()
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    project, _actor = await _seed_direct_context_project(session)
    service, _job_port = _migration_service(session)

    with pytest.raises(ConflictError, match="only for RAG"):
        await service.get_active_source(project.id, KnowledgeCategoryKey.JOBS)


async def test_activation_defers_the_legacy_card_until_cutover(monkeypatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    project, actor = await _seed_direct_context_project(session)
    service, _job_port = _migration_service(session)
    legacy_card = dict(project.index_card)

    revision, _job_id = await service.stage_replacement(
        project_id=project.id,
        category_key=KnowledgeCategoryKey.JOBS,
        filename="jobs.yaml",
        source_yaml=_jobs_yaml(),
        actor=actor,
    )
    await service.activate_revision(revision.id, _UnitEmbedder())

    # Activation landed the revision but wrote nothing of the projection: the
    # single-page card stays exactly as the cutover snapshot will capture it.
    assert revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert revision.quality_result["projection"] == "deferred_until_cutover"
    assert project.index_card == legacy_card
    assert project.summary == "Legacy single-page summary"
    assert project.category_authority_started is False
