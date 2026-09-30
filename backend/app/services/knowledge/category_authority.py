"""Category-authority cutover and rollback for catalog-managed Projects.

Cutover flips a Project's knowledge authority from its legacy KB-version pointer
to its per-category revision pointers, and rollback restores the exact pointer
set captured in ``projects.category_cutover_snapshot``. It is the highest
blast-radius operation in the knowledge package — it rewrites category pointers,
project projection fields and revision statuses — so it lives here, apart from
the revision CRUD in ``category_service``, which delegates to it.

The project / row-lock preconditions these operations share with the CRUD
methods live here too, so "which project may be touched" has one owner. A
category write is admitted for ANY knowledge mode: a legacy DIRECT_CONTEXT
project is staged, cleared and cut over while it still reads as DIRECT_CONTEXT,
and the cutover itself moves its knowledge base to RAG (rollback restores it),
which is what the console panel keys on when choosing the category catalog.
Only the read of an active category source stays RAG-only.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.models.user import User
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.services.audit_service import record_audit
from app.services.knowledge.category_contracts import CATEGORY_DEFINITIONS
from app.services.knowledge.category_projections import CategoryProjectionWriter
from app.shared.domain.errors import ConflictError, NotFoundError

RepairCaches = Callable[[], Awaitable[None]]


async def require_rag_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Load the Project and assert it is owned by a RAG knowledge base."""
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    knowledge_base = (
        await db.get(KnowledgeBase, project.knowledge_base_id) if project.knowledge_base_id else None
    )
    if knowledge_base is None or knowledge_base.mode is not KnowledgeBaseMode.RAG:
        raise ConflictError("This operation is available only for RAG Projects")
    return project


async def require_category_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Load the Project for a category write, whatever its knowledge mode.

    The category lifecycle serves two populations: RAG projects, born
    category-first, and legacy DIRECT_CONTEXT projects being migrated onto the
    catalog. The migration stages, clears and cuts over while the project still
    reads as DIRECT_CONTEXT — the cutover is what moves the knowledge base to
    RAG — so the mode is not a gate here. A missing project stays a 404.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def locked_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def locked_category(
    db: AsyncSession,
    project_id: uuid.UUID,
    category_key: KnowledgeCategoryKey,
) -> KnowledgeCategory:
    category = await db.scalar(
        select(KnowledgeCategory)
        .where(
            KnowledgeCategory.project_id == project_id,
            KnowledgeCategory.category_key == category_key.value,
        )
        .with_for_update()
    )
    if category is None:
        raise NotFoundError("Knowledge category not found")
    return category


def build_cutover_snapshot(
    project: Project,
    categories: list[KnowledgeCategory],
    *,
    knowledge_base_mode: str | None,
) -> dict[str, Any]:
    """Capture everything a rollback needs to restore the pre-cutover authority."""
    return {
        "category_authority_started": project.category_authority_started,
        "active_kb_version_id": (
            str(project.active_kb_version_id) if project.active_kb_version_id else None
        ),
        # The knowledge-base mode the cutover moves to RAG; rollback restores it
        # so the console renders the same panel shape as before the migration.
        "knowledge_base_mode": knowledge_base_mode,
        "category_pointers": {
            category.category_key: (
                str(category.active_revision_id) if category.active_revision_id else None
            )
            for category in categories
        },
        "project_projection": {
            "summary": project.summary,
            "index_card": project.index_card,
            "is_active": project.is_active,
            "discovery_revision": project.discovery_revision,
        },
    }


async def _categories_missing_an_active_revision(
    db: AsyncSession, categories: list[KnowledgeCategory]
) -> list[str]:
    """Category keys that hold neither an active revision nor an explicit clear."""
    missing: list[str] = []
    for category in categories:
        if category.active_revision_id is not None:
            continue
        latest = await db.scalar(
            select(KnowledgeCategoryRevision)
            .where(KnowledgeCategoryRevision.category_id == category.id)
            .order_by(KnowledgeCategoryRevision.revision_no.desc())
            .limit(1)
        )
        if latest is None or latest.status is not KnowledgeCategoryRevisionStatus.CLEARED:
            missing.append(category.category_key)
    expected = {definition.key.value for definition in CATEGORY_DEFINITIONS}
    missing.extend(sorted(expected - {category.category_key for category in categories}))
    return missing


async def cutover_category_authority(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor: User,
    projection_writer: CategoryProjectionWriter,
    repair_caches: RepairCaches,
) -> Project:
    await require_category_project(db, project_id)
    project = await locked_project(db, project_id)
    if project.category_authority_started and project.category_cutover_snapshot:
        await db.commit()
        await repair_caches()
        return project
    knowledge_base = (
        await db.get(KnowledgeBase, project.knowledge_base_id)
        if project.knowledge_base_id
        else None
    )
    categories = list(
        (
            await db.scalars(
                select(KnowledgeCategory)
                .where(KnowledgeCategory.project_id == project_id)
                .order_by(KnowledgeCategory.category_key)
                .with_for_update()
            )
        ).all()
    )
    missing = await _categories_missing_an_active_revision(db, categories)
    if missing:
        raise ConflictError(
            "Category cutover is not ready; prepare or explicitly clear: "
            + ", ".join(sorted(set(missing)))
        )
    project.category_cutover_snapshot = build_cutover_snapshot(
        project,
        categories,
        knowledge_base_mode=(
            knowledge_base.mode.value if knowledge_base is not None else None
        ),
    )
    await projection_writer.rebuild(project_id, categories)
    project.category_authority_started = True
    project.category_cutover_at = datetime.now(UTC)
    # The migration's last step: the catalog now holds the project's knowledge,
    # so the knowledge base stops reading as DIRECT_CONTEXT. The mode is what
    # the console panel and the conversation routing both key on — the panel
    # renders the category catalog, and the agent serves candidates from the
    # active revisions. Rollback puts the captured mode back.
    if knowledge_base is not None and knowledge_base.mode is not KnowledgeBaseMode.RAG:
        knowledge_base.mode = KnowledgeBaseMode.RAG
    await record_audit(
        db,
        action="cutover_project_category_authority",
        actor_id=actor.id,
        target_type="project",
        target_id=str(project.id),
        payload={"ready_category_count": len(categories)},
    )
    await db.commit()
    await repair_caches()
    # The routing catalog caches the KB mode under NS_PREAMBLE; a mode flip is
    # a project write and must invalidate it like every other one.
    await bump_cache_version(NS_PREAMBLE)
    return project


async def rollback_category_authority(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    actor: User,
    projection_writer: CategoryProjectionWriter,
    repair_caches: RepairCaches,
) -> Project:
    await require_category_project(db, project_id)
    project = await locked_project(db, project_id)
    snapshot = project.category_cutover_snapshot
    if not snapshot:
        raise ConflictError("Project has no category cutover snapshot to restore")
    categories = list(
        (
            await db.scalars(
                select(KnowledgeCategory)
                .where(KnowledgeCategory.project_id == project_id)
                .with_for_update()
            )
        ).all()
    )
    snapshot_pointers = snapshot.get("category_pointers") or {}
    for category in categories:
        target_value = snapshot_pointers.get(category.category_key)
        target_id = uuid.UUID(target_value) if target_value else None
        if category.active_revision_id == target_id:
            continue
        if category.active_revision_id is not None:
            current_revision = await db.get(
                KnowledgeCategoryRevision,
                category.active_revision_id,
            )
            if current_revision is not None:
                current_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
        if target_id is not None:
            target_revision = await db.get(KnowledgeCategoryRevision, target_id)
            if target_revision is None or target_revision.category_id != category.id:
                raise ConflictError("Category rollback snapshot is no longer restorable")
            target_revision.status = KnowledgeCategoryRevisionStatus.ACTIVE
        category.active_revision_id = target_id
        category.updated_at = func.now()
    project.category_authority_started = bool(snapshot["category_authority_started"])
    active_version = snapshot.get("active_kb_version_id")
    project.active_kb_version_id = uuid.UUID(active_version) if active_version else None
    await projection_writer.delete_all(project_id)
    project_projection = snapshot.get("project_projection") or {}
    project.summary = project_projection.get("summary")
    project.index_card = project_projection.get("index_card") or {}
    project.is_active = bool(project_projection.get("is_active"))
    project.discovery_revision = int(project_projection.get("discovery_revision") or 0)
    project.category_cutover_at = None
    project.category_cutover_snapshot = None
    await _restore_knowledge_base_mode(db, project, snapshot)
    await record_audit(
        db,
        action="rollback_project_category_authority",
        actor_id=actor.id,
        target_type="project",
        target_id=str(project.id),
        payload={"restored_legacy_authority": not project.category_authority_started},
    )
    await db.commit()
    await repair_caches()
    # Same invalidation as the cutover: the routing catalog caches the KB mode.
    await bump_cache_version(NS_PREAMBLE)
    return project


async def _restore_knowledge_base_mode(
    db: AsyncSession, project: Project, snapshot: dict[str, Any]
) -> None:
    """Put back the knowledge-base mode the cutover captured.

    Snapshots written before the migration path existed carry no mode — those
    projects were already RAG on both sides of the cutover, so leaving the
    knowledge base untouched restores them exactly.
    """
    mode_value = snapshot.get("knowledge_base_mode")
    if mode_value is None or not project.knowledge_base_id:
        return
    if mode_value not in {mode.value for mode in KnowledgeBaseMode}:
        return
    knowledge_base = await db.get(KnowledgeBase, project.knowledge_base_id)
    if knowledge_base is not None and knowledge_base.mode.value != mode_value:
        knowledge_base.mode = KnowledgeBaseMode(mode_value)
