"""Database proof for migrating a legacy DIRECT_CONTEXT project onto the
12-category catalog through one brief-shaped ingest chain.

The journey the console drives: stage the carried categories (a DIRECT_CONTEXT
project owns no category rows — staging seeds them), activate them (a legacy
card defers its projection), explicitly clear the categories the brief does not
carry, cut the authority over — the cutover moves the knowledge base out of
DIRECT_CONTEXT, which is what the console panel and the conversation routing
key on — and keep rollback able to put the single-page world back exactly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevisionStatus,
)
from app.models.user import Role, User
from app.project_knowledge.application.jobs import (
    ProjectKnowledgeJobRequest,
    ProjectKnowledgeJobs,
)
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
)
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.shared.domain.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration


class _Embedder:
    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3072 for _ in texts]


class _RecordingJobPort:
    """Staging must hand each revision to the queue and keep its receipt."""

    def __init__(self) -> None:
        self.requests: list[ProjectKnowledgeJobRequest] = []

    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str:
        self.requests.append(request)
        return f"job-{len(self.requests)}"


async def _seed_direct_context_project(
    integration_session,
) -> tuple[User, Project, KnowledgeBase]:
    actor = User(
        email=f"migrate-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        name="Rorze",
        slug=f"rorze-{uuid.uuid4().hex}",
        category_authority_started=False,
        summary="Legacy single-page summary",
        index_card={
            "summary": "Legacy single-page summary",
            "highlights": ["Có xe đưa đón"],
        },
    )
    integration_session.add_all([actor, project])
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Rorze Knowledge",
        slug=f"rorze-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        project_id=project.id,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    await integration_session.commit()
    return actor, project, knowledge_base


def _jobs_yaml() -> str:
    return (
        "category: jobs\njobs:\n  - id: migrated-operator\n"
        "    title: Vận hành máy CNC\n    location: Hải Phòng\n"
    )


async def _category_count(integration_session, project_id) -> int:
    return int(
        await integration_session.scalar(
            select(func.count())
            .select_from(KnowledgeCategory)
            .where(KnowledgeCategory.project_id == project_id)
        )
    )


async def test_direct_context_project_stages_cuts_over_and_rolls_back(
    integration_session,
) -> None:
    actor, project, knowledge_base = await _seed_direct_context_project(
        integration_session
    )
    job_port = _RecordingJobPort()
    service = KnowledgeCategoryService(
        integration_session,
        jobs=ProjectKnowledgeJobs(job_port),
        enforce_retrieval_selftest=False,
    )

    # The catalog reads before any write: twelve empty categories, no rows yet.
    catalog = await service.list_catalog(project.id)
    assert len(catalog) == 12
    assert all(item.active_revision_id is None for item in catalog)
    assert await _category_count(integration_session, project.id) == 0

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
    # Seeding rides the first stage: every category row now exists, so the
    # cutover readiness check below is satisfiable.
    assert await _category_count(integration_session, project.id) == 12

    # A missing project stays a 404 — the relaxed mode gate does not widen that.
    with pytest.raises(NotFoundError):
        await service.stage_replacement(
            project_id=uuid.uuid4(),
            category_key=KnowledgeCategoryKey.JOBS,
            filename="jobs.yaml",
            source_yaml=_jobs_yaml(),
            actor=actor,
        )

    await service.activate_revision(revision.id, _Embedder())
    await integration_session.refresh(revision)
    await integration_session.refresh(project)
    assert revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    # The legacy single-page card is protected until the cutover replaces it.
    assert revision.quality_result["projection"] == "deferred_until_cutover"
    assert project.index_card["summary"] == "Legacy single-page summary"
    assert project.category_authority_started is False

    # The categories the brief does not carry are cleared explicitly — the
    # preparation the cutover readiness check names ("prepare or explicitly
    # clear"). A cleared category holds an explicit empty state, not a gap.
    for definition in CATEGORY_DEFINITIONS:
        if definition.key is KnowledgeCategoryKey.JOBS:
            continue
        await service.clear(
            project_id=project.id,
            category_key=definition.key,
            actor=actor,
        )

    migrated = await service.cutover_category_authority(
        project_id=project.id, actor=actor
    )
    await integration_session.refresh(knowledge_base)
    await integration_session.refresh(project)
    assert migrated.category_authority_started is True
    assert migrated.category_cutover_snapshot["knowledge_base_mode"] == "DIRECT_CONTEXT"
    # The cutover is what ends the single-page rendering: the knowledge base
    # leaves DIRECT_CONTEXT, so the project reads as a catalog project on both
    # the console panel and the conversation routing.
    assert knowledge_base.mode is KnowledgeBaseMode.RAG
    assert project.summary == "Rorze đang tuyển Vận hành máy CNC tại Hải Phòng."
    assert project.category_cutover_at is not None

    rolled_back = await service.rollback_category_authority(
        project_id=project.id, actor=actor
    )
    await integration_session.refresh(knowledge_base)
    await integration_session.refresh(project)
    assert rolled_back.category_authority_started is False
    assert rolled_back.summary == "Legacy single-page summary"
    assert rolled_back.index_card["highlights"] == ["Có xe đưa đón"]
    assert knowledge_base.mode is KnowledgeBaseMode.DIRECT_CONTEXT


async def test_cutover_still_requires_every_category_prepared(integration_session) -> None:
    """The relaxed mode gate keeps cutover's own validation: a DIRECT_CONTEXT
    project whose brief carried only some categories cannot cut over until the
    rest are prepared or cleared."""
    actor, project, _knowledge_base = await _seed_direct_context_project(
        integration_session
    )
    service = KnowledgeCategoryService(
        integration_session,
        jobs=ProjectKnowledgeJobs(_RecordingJobPort()),
        enforce_retrieval_selftest=False,
    )
    revision, _job_id = await service.stage_replacement(
        project_id=project.id,
        category_key=KnowledgeCategoryKey.JOBS,
        filename="jobs.yaml",
        source_yaml=_jobs_yaml(),
        actor=actor,
    )
    await service.activate_revision(revision.id, _Embedder())

    with pytest.raises(ConflictError, match="not ready"):
        await service.cutover_category_authority(project_id=project.id, actor=actor)
    # Nothing moved: the project still reads as a single-page project.
    await integration_session.refresh(project)
    assert project.category_authority_started is False
    assert project.category_cutover_snapshot is None
    await integration_session.refresh(_knowledge_base)
    assert _knowledge_base.mode is KnowledgeBaseMode.DIRECT_CONTEXT
