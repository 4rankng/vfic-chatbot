"""Recruitment knowledge-project business logic: CRUD + master-index rebuild.

Extracted from the legacy monolithic ``project_service.py`` into the
``services/project/`` package. The managed-FAQ and feature/catalog concerns live
in :mod:`app.services.project.faq` and :mod:`app.services.project.features`;
this service composes them and forwards via thin delegates. Raw SQL lives in
:mod:`app.services.project.repository`; pure row→schema mappers in
:mod:`app.services.project.mapping`.

Raises domain exceptions (:class:`NotFoundError`, :class:`ConflictError`,
:class:`ForbiddenError`, :class:`UpstreamError`) — the API routes map these to HTTP
status codes.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
)
from app.models.user import User
from app.schemas.projects import (
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureReadiness,
    FeatureUpdate,
    ProjectCreate,
    ProjectFaqCreate,
    ProjectFaqOut,
    ProjectFaqResponse,
    ProjectFaqUpdate,
    ProjectOut,
    ProjectUpdate,
)
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError
from app.services.knowledge.repository import JobFeatureValueRepo
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.project.faq import ProjectFaqService
from app.services.project.features import ProjectFeatureService
from app.services.project.single_page_external_sources import SinglePageExternalSourceService
from app.services.project.repository import ProjectRepository, require_project
from app.services.knowledge_base_service import KnowledgeBaseService

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)
        self.faqs = ProjectFaqService(self.db)
        self.features = ProjectFeatureService(self.db)
        self.single_page_external_sources = SinglePageExternalSourceService(self.db)

    async def list(
        self,
        is_active: bool | None = None,
        *,
        page: int = 1,
        per_page: int = 25,
        sort_by: str | None = None,
        order: str | None = "desc",
        q: str | None = None,
    ) -> tuple[list[Project], int]:
        query = select(Project)
        if is_active is not None:
            query = query.where(Project.is_active == is_active)
        if q:
            pat = f"%{q.strip()}%"
            ua = func.extensions.unaccent
            query = query.where(
                ua(Project.name).ilike(ua(pat))
                | ua(Project.slug).ilike(ua(pat))
                | ua(Project.summary).ilike(ua(pat))
            )
        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        sort_map = {
            "created_at": Project.created_at,
            "updated_at": Project.updated_at,
            "name": Project.name,
            "is_active": Project.is_active,
        }
        sort_col = sort_map.get((sort_by or "").lower()) or Project.created_at
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        rows = (
            await self.db.scalars(
                query.order_by(order_expr).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def list_with_readiness(
        self,
        is_active: bool | None = None,
        *,
        page: int = 1,
        per_page: int = 25,
        sort_by: str | None = None,
        order: str | None = "desc",
        q: str | None = None,
    ) -> tuple[list[ProjectOut], int]:
        """List projects with per-project feature readiness attached.

        One batched ``readiness_by_project`` query — no N+1. The catalog total is the
        active-feature count.
        """
        rows, row_total = await self.list(
            is_active,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            order=order,
            q=q,
        )
        repo = JobFeatureValueRepo(self.db)
        ready = await repo.readiness_by_project([p.id for p in rows])
        total = await repo.active_catalog_size()
        doc_counts = await self.repo.knowledge_document_counts([p.id for p in rows])
        modes = await self._knowledge_modes([p.knowledge_base_id for p in rows])
        out: list[ProjectOut] = []
        for p in rows:
            o = ProjectOut.model_validate(p)
            o.knowledge_mode = modes.get(p.knowledge_base_id)
            o.knowledge_document_count = doc_counts.get(p.id, 0)
            o.feature_readiness = FeatureReadiness(ready=ready.get(p.id, 0), total=total)
            out.append(o)
        return out, row_total

    async def get(self, project_id: uuid.UUID) -> Project:
        return await self._require_project(project_id)

    async def get_with_readiness(self, project_id: uuid.UUID) -> ProjectOut:
        """Single-project get with feature readiness attached."""
        proj = await self._require_project(project_id)
        repo = JobFeatureValueRepo(self.db)
        ready = await repo.readiness_by_project([proj.id])
        total = await repo.active_catalog_size()
        doc_counts = await self.repo.knowledge_document_counts([proj.id])
        o = ProjectOut.model_validate(proj)
        o.knowledge_mode = (await self._knowledge_modes([proj.knowledge_base_id])).get(
            proj.knowledge_base_id
        )
        o.knowledge_document_count = doc_counts.get(proj.id, 0)
        o.feature_readiness = FeatureReadiness(ready=ready.get(proj.id, 0), total=total)
        return o

    async def create(self, body: ProjectCreate, admin: User) -> Project:
        name = body.name.strip()
        existing = await self.repo.find_by_name(name)
        if existing is not None:
            raise ConflictError("Project name already exists")

        proj = Project(
            slug=body.slug.strip(),
            name=name,
            is_active=body.is_active,
            aliases=[value.strip() for value in body.aliases if value.strip()],
            summary=(body.discovery_card or {}).get("summary"),
            index_card=body.discovery_card or {},
        )
        self.db.add(proj)
        try:
            await self.db.flush()
            knowledge_base = KnowledgeBase(
                project_id=proj.id,
                name=f"{name} Knowledge",
                slug=f"{body.slug.strip()}-kb",
                mode=body.knowledge_mode,
                created_by=admin.id,
            )
            self.db.add(knowledge_base)
            await self.db.flush()
            proj.knowledge_base_id = knowledge_base.id
            if body.knowledge_mode is KnowledgeBaseMode.RAG:
                self.db.add_all(
                    [
                        KnowledgeCategory(project_id=proj.id, category_key=key.value)
                        for key in KnowledgeCategoryKey
                    ]
                )
            await record_audit(
                self.db,
                action="create_project",
                actor_id=admin.id,
                target_type="project",
                target_id=str(proj.id),
                payload={"knowledge_mode": body.knowledge_mode.value},
            )
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 — unique slug violation etc.
            await self.db.rollback()
            raise ConflictError(f"project create failed: {exc}") from exc
        await self.db.refresh(proj)
        await bump_cache_version(NS_PREAMBLE)
        return proj

    async def update(self, project_id: uuid.UUID, body: ProjectUpdate, actor: User) -> Project:
        proj = await self._require_project(project_id)
        if body.name is not None:
            proj.name = body.name.strip()
        if body.is_active is not None:
            if body.is_active:
                await self._require_activation_ready(proj)
            proj.is_active = body.is_active
        if body.aliases is not None:
            proj.aliases = [value.strip() for value in body.aliases if value.strip()]
        if "discovery_card" in body.model_fields_set:
            mode = (await self._knowledge_modes([proj.knowledge_base_id])).get(
                proj.knowledge_base_id
            )
            if mode is not KnowledgeBaseMode.DIRECT_CONTEXT:
                raise ConflictError("RAG discovery cards are derived from active categories")
            if not body.discovery_card:
                raise ConflictError("Single-page Projects require a discovery card")
            proj.index_card = body.discovery_card
            proj.summary = body.discovery_card.get("summary")
            proj.discovery_revision += 1
        await record_audit(
            self.db,
            action="update_project",
            actor_id=actor.id,
            target_type="project",
            target_id=str(proj.id),
        )
        await self.db.commit()
        await self.db.refresh(proj)
        await bump_cache_version(NS_PREAMBLE)
        return proj

    async def delete(self, project_id: uuid.UUID, admin: User) -> None:
        proj = await self._require_project(project_id)
        await record_audit(
            self.db,
            action="delete_project",
            actor_id=admin.id,
            target_type="project",
            target_id=str(proj.id),
        )
        await self.db.delete(proj)
        await self.db.commit()
        await bump_cache_version(NS_PREAMBLE)

    async def get_single_page(self, project_id: uuid.UUID):
        from app.models.knowledge import KnowledgeBaseDirectFile

        project = await self._require_project(project_id)
        knowledge_base = await self._require_project_mode(
            project,
            KnowledgeBaseMode.DIRECT_CONTEXT,
        )
        direct_file = await self.db.scalar(
            select(KnowledgeBaseDirectFile).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
        if direct_file is None:
            raise NotFoundError("Single-page knowledge has not been added yet")
        return direct_file

    async def replace_single_page(
        self,
        project_id: uuid.UUID,
        body: DirectContextFileUpsert,
        actor: User,
    ):
        project = await self._require_project(project_id)
        knowledge_base = await self._require_project_mode(
            project,
            KnowledgeBaseMode.DIRECT_CONTEXT,
        )
        activating = not project.is_active
        if activating:
            if not project.index_card:
                raise ConflictError("Single-page Project needs a discovery card before activation")
            project.is_active = True
            await record_audit(
                self.db,
                action="update_project",
                actor_id=actor.id,
                target_type="project",
                target_id=str(project.id),
                payload={"is_active": True, "reason": "single_page_ready"},
            )
        direct_file = await KnowledgeBaseService(self.db).upsert_direct_file(
            knowledge_base.id,
            body,
            actor,
        )
        if activating:
            await bump_cache_version(NS_PREAMBLE)
        return direct_file

    async def list_single_page_external_sources(
        self, project_id: uuid.UUID
    ):
        return await self.single_page_external_sources.list_sources(project_id)

    async def create_single_page_external_source(self, project_id: uuid.UUID, body, actor: User):
        return await self.single_page_external_sources.create_source(project_id, body, actor)

    async def run_single_page_external_source_now(
        self, project_id: uuid.UUID, source_id: uuid.UUID, actor: User
    ) -> str:
        return await self.single_page_external_sources.run_now(project_id, source_id, actor)

    async def delete_single_page_external_source(
        self, project_id: uuid.UUID, source_id: uuid.UUID, actor: User
    ) -> None:
        await self.single_page_external_sources.delete_source(project_id, source_id, actor)

    async def reindex(self, project_id: uuid.UUID) -> Project:
        """Rebuild this project's catalog card (the master-index entry) from usable units."""
        await self._require_project(project_id)
        raise ConflictError(
            "Project knowledge is rebuilt only by replacing its Single-page content or category YAML"
        )

    # ── FAQ delegates ──────────────────────────────────────────────────────

    async def list_faq(self, project_id: uuid.UUID, *, limit: int = 12) -> ProjectFaqResponse:
        return await self.faqs.list_faq(project_id, limit=limit)

    async def create_faq(
        self, project_id: uuid.UUID, body: ProjectFaqCreate, actor: User
    ) -> ProjectFaqOut:
        return await self.faqs.create_faq(project_id, body, actor)

    async def update_faq(
        self, project_id: uuid.UUID, chunk_id: uuid.UUID, body: ProjectFaqUpdate, actor: User
    ) -> ProjectFaqOut:
        return await self.faqs.update_faq(project_id, chunk_id, body, actor)

    async def delete_faq(self, project_id: uuid.UUID, chunk_id: uuid.UUID, actor: User) -> None:
        return await self.faqs.delete_faq(project_id, chunk_id, actor)

    # ── Feature / catalog delegates ────────────────────────────────────────

    async def list_features(self, project_id: uuid.UUID) -> FeatureListResponse:
        return await self.features.list_features(project_id)

    async def list_bus_timetable(
        self, project_id: uuid.UUID, *, page: int = 1, per_page: int = 6
    ) -> BusTimetableResponse:
        return await self.features.list_bus_timetable(project_id, page=page, per_page=per_page)

    async def update_feature(
        self, project_id: uuid.UUID, feature_id: uuid.UUID, body: FeatureUpdate, actor: User
    ) -> FeatureOut:
        return await self.features.update_feature(project_id, feature_id, body, actor)

    async def extract_features(self, project_id: uuid.UUID, admin: User) -> FeatureListResponse:
        return await self.features.extract_features(project_id, admin)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        return await require_project(self.db, project_id)

    async def _knowledge_modes(
        self, knowledge_base_ids: list[uuid.UUID | None]
    ) -> dict[uuid.UUID, KnowledgeBaseMode]:
        ids = [value for value in knowledge_base_ids if value is not None]
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(KnowledgeBase.id, KnowledgeBase.mode).where(KnowledgeBase.id.in_(ids))
            )
        ).all()
        return dict(rows)

    async def _require_project_mode(
        self,
        project: Project,
        expected: KnowledgeBaseMode,
    ) -> KnowledgeBase:
        knowledge_base = (
            await self.db.get(KnowledgeBase, project.knowledge_base_id)
            if project.knowledge_base_id
            else None
        )
        if knowledge_base is None or knowledge_base.mode is not expected:
            raise ConflictError(f"This operation requires a {expected.value} Project")
        return knowledge_base

    async def _require_activation_ready(self, project: Project) -> None:
        modes = await self._knowledge_modes([project.knowledge_base_id])
        mode = modes.get(project.knowledge_base_id)
        if mode is KnowledgeBaseMode.DIRECT_CONTEXT:
            if not project.index_card:
                raise ConflictError("Single-page Project needs a discovery card before activation")
            direct_file = await self.db.scalar(
                select(KnowledgeBaseDirectFile.id).where(
                    KnowledgeBaseDirectFile.knowledge_base_id == project.knowledge_base_id
                )
            )
            if direct_file is None:
                raise ConflictError("Single-page Project needs its page before activation")
            return
        if mode is KnowledgeBaseMode.RAG:
            category = await self.db.scalar(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project.id,
                    KnowledgeCategory.category_key == KnowledgeCategoryKey.JOBS.value,
                )
            )
            revision = (
                await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
                if category and category.active_revision_id
                else None
            )
            if revision is None or not revision.normalized_payload.get("jobs"):
                raise ConflictError("RAG Project needs an active Jobs category before activation")
            return
        raise ConflictError("Project has no owned knowledge base")
