"""Real database proof that migration clears cannot erase later admin writes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeChunk,
)
from app.models.user import Role, User
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.shared.domain.errors import ConflictError

pytestmark = pytest.mark.integration


class _Embedder:
    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3072 for _ in texts]


@pytest.fixture
async def category_sessions(integration_database):
    # Separate sessions commit real transactions, as separate admin requests do.
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed(session_factory):
    async with session_factory() as db:
        actor = User(
            email=f"conditional-clear-{uuid.uuid4().hex}@example.test",
            password_hash="not-used",
            role=Role.admin,
        )
        project = Project(
            name="Nhà máy giữ nguyên thông tin",
            slug=f"conditional-clear-{uuid.uuid4().hex}",
            category_authority_started=False,
            index_card={"summary": "Thông tin đã lưu"},
        )
        db.add_all([actor, project])
        await db.flush()
        base = KnowledgeBase(
            name=project.name,
            slug=f"conditional-clear-kb-{uuid.uuid4().hex}",
            mode=KnowledgeBaseMode.DIRECT_CONTEXT,
            project_id=project.id,
            created_by=actor.id,
        )
        category = KnowledgeCategory(project_id=project.id, category_key="jobs")
        db.add_all([base, category])
        await db.flush()
        project.knowledge_base_id = base.id
        await db.commit()
        return actor, project.id, category.id


async def _manual_revision(session_factory, actor, project_id, *, activate: bool):
    async with session_factory() as db:
        service = KnowledgeCategoryService(db, enforce_retrieval_selftest=False)
        revision, _ = await service.stage_replacement(
            project_id=project_id,
            category_key=KnowledgeCategoryKey.JOBS,
            filename="jobs.md",
            source_markdown=(
                '---\nschema_version: "1.0"\ncategory: jobs\n---\n\n'
                "## jobs\n\n### record: manual-operator\n"
                'title: "Vận hành máy CNC"\nlocation: "Hải Phòng"\n'
            ),
            actor=actor,
            schedule=False,
        )
        if activate:
            await service.activate_revision(revision.id, _Embedder())
        return revision.id


@pytest.mark.parametrize("activate", [False, True], ids=["staged", "active"])
async def test_only_if_empty_clear_rejects_later_manual_revision(
    category_sessions, activate: bool
) -> None:
    actor, project_id, category_id = await _seed(category_sessions)
    # Migration first observes an empty category, then another request saves it.
    async with category_sessions() as reader:
        catalog = await KnowledgeCategoryService(reader).list_catalog(project_id)
        jobs = next(item for item in catalog if item.key is KnowledgeCategoryKey.JOBS)
        assert jobs.latest_revision_no is None
        assert jobs.active_revision_id is None
    revision_id = await _manual_revision(category_sessions, actor, project_id, activate=activate)

    async with category_sessions() as migration:
        with pytest.raises(ConflictError, match="Danh mục đã thay đổi"):
            await KnowledgeCategoryService(migration).clear(
                project_id=project_id,
                category_key=KnowledgeCategoryKey.JOBS,
                actor=actor,
                expected_revision_no=0,
            )
        await migration.rollback()

    async with category_sessions() as verifier:
        category = await verifier.get(KnowledgeCategory, category_id)
        revision = await verifier.get(KnowledgeCategoryRevision, revision_id)
        assert category.active_revision_id == (revision_id if activate else None)
        assert revision.status is (
            KnowledgeCategoryRevisionStatus.ACTIVE
            if activate
            else KnowledgeCategoryRevisionStatus.STAGED
        )
        assert revision.normalized_payload["jobs"][0]["title"] == "Vận hành máy CNC"
        assert (
            await verifier.scalar(
                select(func.count())
                .select_from(KnowledgeCategoryRevision)
                .where(KnowledgeCategoryRevision.category_id == category_id)
            )
            == 1
        )
        if activate:
            assert (
                await verifier.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .where(KnowledgeChunk.category_revision_id == revision_id)
                )
                > 0
            )


async def test_only_if_empty_clear_initializes_genuinely_empty_category(
    category_sessions,
) -> None:
    actor, project_id, category_id = await _seed(category_sessions)
    async with category_sessions() as db:
        cleared = await KnowledgeCategoryService(db).clear(
            project_id=project_id,
            category_key=KnowledgeCategoryKey.JOBS,
            actor=actor,
            expected_revision_no=0,
        )
        assert cleared.category_id == category_id
        assert cleared.revision_no == 1
        assert cleared.status is KnowledgeCategoryRevisionStatus.CLEARED
        assert cleared.normalized_payload["jobs"] == []


async def test_manual_clear_without_precondition_keeps_existing_behavior(
    category_sessions,
) -> None:
    actor, project_id, category_id = await _seed(category_sessions)
    revision_id = await _manual_revision(category_sessions, actor, project_id, activate=True)
    async with category_sessions() as db:
        cleared = await KnowledgeCategoryService(db).clear(
            project_id=project_id,
            category_key=KnowledgeCategoryKey.JOBS,
            actor=actor,
        )
        assert cleared.revision_no == 2
        assert cleared.status is KnowledgeCategoryRevisionStatus.CLEARED
        category = await db.get(KnowledgeCategory, category_id)
        revision = await db.get(KnowledgeCategoryRevision, revision_id)
        assert category.active_revision_id is None
        assert revision.status is KnowledgeCategoryRevisionStatus.ARCHIVED
