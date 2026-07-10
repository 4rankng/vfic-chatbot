"""Project ("product catalog") business logic: CRUD + master-index rebuild.

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
from app.models.persona import Persona
from app.models.user import Role, User
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
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, UpstreamError
from app.services.knowledge.repository import JobFeatureValueRepo
from app.services.project.faq import ProjectFaqService
from app.services.project.features import ProjectFeatureService
from app.services.project.repository import ProjectRepository, require_project

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)
        self.faqs = ProjectFaqService(self.db)
        self.features = ProjectFeatureService(self.db)

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
        out: list[ProjectOut] = []
        for p in rows:
            o = ProjectOut.model_validate(p)
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
        o.knowledge_document_count = doc_counts.get(proj.id, 0)
        o.feature_readiness = FeatureReadiness(ready=ready.get(proj.id, 0), total=total)
        return o

    async def create(self, body: ProjectCreate, admin: User) -> Project:
        name = body.name.strip()
        existing = await self.repo.find_by_name(name)
        if existing is not None:
            return existing

        proj = Project(slug=body.slug.strip(), name=name, is_active=body.is_active)
        self.db.add(proj)
        try:
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 — unique slug violation etc.
            await self.db.rollback()
            raise ConflictError(f"project create failed: {exc}") from exc
        await record_audit(
            self.db,
            action="create_project",
            actor_id=admin.id,
            target_type="project",
            target_id=str(proj.id),
        )
        await self.db.commit()
        await self.db.refresh(proj)
        await bump_cache_version(NS_PREAMBLE)
        return proj

    async def update(self, project_id: uuid.UUID, body: ProjectUpdate, actor: User) -> Project:
        proj = await self._require_project(project_id)
        if body.name is not None:
            proj.name = body.name.strip()
        if body.is_active is not None:
            proj.is_active = body.is_active
        if "default_persona_id" in body.model_fields_set:
            if actor.role != Role.admin:
                raise ForbiddenError("admin only")
            if body.default_persona_id is not None:
                persona = await self.db.get(Persona, body.default_persona_id)
                if persona is None:
                    raise NotFoundError("Agent not found")
            proj.default_persona_id = body.default_persona_id
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

    async def reindex(self, project_id: uuid.UUID) -> Project:
        """Rebuild this project's catalog card (the master-index entry) from usable units."""
        proj = await self._require_project(project_id)
        # Imported lazily so langchain/provider deps stay out of the web-process import path.
        from app.core.config import get_settings
        from app.graph.clients import build_embedder
        from app.graph.factories import make_minimax_llm_json
        from app.services.integration_settings import IntegrationSettingsService
        from app.services.knowledge import KnowledgePipeline

        try:
            integration_settings = IntegrationSettingsService(self.db)
            minimax_config = await integration_settings.resolve_minimax()
            openrouter_config = await integration_settings.resolve_openrouter()
            # Web sync path: cap the LLM call at the request timeout (60s), NOT the digest
            # ceiling (180s) — this runs in the web process (web_concurrency=2), so a slow
            # MiniMax index rebuild must not stall the API.
            await KnowledgePipeline(
                self.db,
                build_embedder(openrouter_api_key=openrouter_config.api_key),
                make_minimax_llm_json(
                    minimax_api_key=minimax_config.api_key,
                    openrouter_api_key=openrouter_config.api_key,
                ),
                call_timeout=get_settings().active_llm_request_timeout,
            ).build_project_index(proj.id)
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(f"index rebuild failed: {exc}") from exc
        await self.db.refresh(proj)
        return proj

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
