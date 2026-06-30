"""Project ("product catalog") business logic: CRUD + master-index rebuild + worker
product-feature CRUD/re-extraction.

Extracted from the legacy monolithic ``project_service.py`` into the
``services/project/`` package. Raw SQL lives in :mod:`app.services.project.repository`;
pure row→schema mappers in :mod:`app.services.project.mapping`.

Raises domain exceptions (:class:`NotFoundError`, :class:`ConflictError`,
:class:`ForbiddenError`, :class:`UpstreamError`) — the API routes map these to HTTP
status codes.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.persona import Persona
from app.models.user import Role, User
from app.schemas.projects import (
    BusRouteOut,
    BusStopOut,
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureReadiness,
    ProjectFaqOut,
    ProjectFaqResponse,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    FeatureUpdate,
)
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, UpstreamError
from app.services.knowledge import sync_project_highlights
from app.services.knowledge.repository import JobFeatureValueRepo
from app.services.project.mapping import _faq_answer_from_content, _feature_from_row
from app.services.project.repository import ProjectRepository, require_project

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)

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

    async def reindex(self, project_id: uuid.UUID) -> Project:
        """Rebuild this project's catalog card (the master-index entry) from usable units."""
        proj = await self._require_project(project_id)
        # Imported lazily so langchain/google deps stay out of the web-process import path.
        from app.core.config import get_settings
        from app.graph.clients import GeminiEmbedder
        from app.graph.factories import make_minimax_llm_json
        from app.services.knowledge import KnowledgePipeline

        try:
            # Web sync path: cap the LLM call at the request timeout (60s), NOT the digest
            # ceiling (180s) — this runs in the web process (web_concurrency=2), so a slow
            # MiniMax index rebuild must not stall the API.
            await KnowledgePipeline(
                self.db,
                GeminiEmbedder(),
                make_minimax_llm_json(),
                call_timeout=get_settings().active_llm_request_timeout,
            ).build_project_index(proj.id)
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(f"index rebuild failed: {exc}") from exc
        await self.db.refresh(proj)
        return proj

    async def list_features(self, project_id: uuid.UUID) -> FeatureListResponse:
        """List the project's active extracted worker product features (catalog order)."""
        await self._require_project(project_id)
        rows = await JobFeatureValueRepo(self.db).list_for_project(project_id)
        return FeatureListResponse(data=[_feature_from_row(r) for r in rows], total=len(rows))

    async def list_bus_timetable(
        self, project_id: uuid.UUID, *, page: int = 1, per_page: int = 6
    ) -> BusTimetableResponse:
        """List one page of structured bus routes with ordered stops."""
        await self._require_project(project_id)
        page = max(1, page)
        per_page = min(25, max(1, per_page))
        total = await self.repo.count_bus_routes(project_id)
        if total == 0:
            return BusTimetableResponse(data=[], total=0, page=page, per_page=per_page)

        route_rows = await self.repo.list_bus_routes(
            project_id, limit=per_page, offset=(page - 1) * per_page
        )
        if not route_rows:
            return BusTimetableResponse(data=[], total=total, page=page, per_page=per_page)

        route_ids = [str(row["id"]) for row in route_rows]
        stop_rows = await self.repo.list_bus_stops(route_ids)
        stops_by_route: dict[uuid.UUID, list[BusStopOut]] = {}
        for row in stop_rows:
            route_id = row["route_id"]
            stops_by_route.setdefault(route_id, []).append(
                BusStopOut(
                    id=row["id"],
                    stop_order=row["stop_order"],
                    stop_name=row["stop_name"],
                    scheduled_time=row["scheduled_time"],
                )
            )

        data = [
            BusRouteOut(
                id=row["id"],
                route_name=row["route_name"],
                route_no=row["route_no"],
                route_variant=row["route_variant"] or "",
                shift=row["shift"],
                direction=row["direction"],
                area=row["area"],
                mode=row["mode"],
                source_page=row["source_page"] or "",
                notes=row["notes"],
                stops=stops_by_route.get(row["id"], []),
            )
            for row in route_rows
        ]
        return BusTimetableResponse(data=data, total=total, page=page, per_page=per_page)

    async def list_faq(self, project_id: uuid.UUID, *, limit: int = 12) -> ProjectFaqResponse:
        """List published FAQ chunks for a project."""
        await self._require_project(project_id)
        limit = min(50, max(1, limit))
        rows = await self.repo.list_faq_chunks(project_id, limit=limit)
        data = [
            ProjectFaqOut(
                id=row["id"],
                question=(row["questions"] or ["FAQ"])[0],
                answer=_faq_answer_from_content(row["content"], (row["questions"] or ["FAQ"])[0]),
                source_name=row["file_name"],
                source_anchor=row["source_anchor"],
            )
            for row in rows
        ]
        return ProjectFaqResponse(data=data, total=len(data))

    async def update_feature(
        self, project_id: uuid.UUID, feature_id: uuid.UUID, body: FeatureUpdate, actor: User
    ) -> FeatureOut:
        """Recruiter/admin edit of one extracted feature value; re-syncs product highlights."""
        repo = JobFeatureValueRepo(self.db)
        if not await repo.exists_for_project(feature_id, project_id):
            raise NotFoundError("feature value not found")

        sets: list[str] = []
        params: dict[str, Any] = {"fid": str(feature_id)}
        if body.value_text is not None:
            sets.append("value_text = :value_text")
            params["value_text"] = body.value_text
            sets.append("is_missing = false")  # an admin-provided value is no longer missing
        if body.value_json is not None:
            sets.append("value_json = CAST(:value_json AS jsonb)")
            params["value_json"] = json.dumps(body.value_json, ensure_ascii=False)
        if body.is_highlight is not None:
            sets.append("is_highlight = :is_highlight")
            params["is_highlight"] = body.is_highlight
        if body.is_missing is not None:
            sets.append("is_missing = :is_missing")
            params["is_missing"] = body.is_missing
        if body.needs_clarification is not None:
            sets.append("needs_clarification = :needs_clarification")
            params["needs_clarification"] = body.needs_clarification
        if body.evidence_text is not None:
            sets.append("evidence_text = :evidence_text")
            params["evidence_text"] = body.evidence_text

        if sets:
            await repo.update_fields(sets, params)
            await record_audit(
                self.db,
                action="update_project_feature",
                actor_id=actor.id,
                target_type="job_feature_value",
                target_id=str(feature_id),
            )
            await self.db.commit()
            await sync_project_highlights(self.db, project_id)

        row = await repo.get(feature_id)
        assert row is not None  # noqa: S101 — just verified existence above
        return _feature_from_row(row)

    async def extract_features(self, project_id: uuid.UUID, admin: User) -> FeatureListResponse:
        """Synchronously re-extract active product features from the project's latest posting.

        Persona-pattern: one blocking MiniMax call in the web process (~5-10s). Merges
        the latest document's concrete values into the project's feature profile without
        erasing older useful answers for features the latest document omits.
        """
        await self._require_project(project_id)
        doc = await self.repo.get_latest_document_with_text(project_id)
        if doc is None:
            raise ConflictError(
                "no source document with text for this project — upload a posting first"
            )
        # Imported lazily (langchain/google deps kept out of the web-process import path).
        from app.core.config import get_settings
        from app.graph.clients import GeminiEmbedder
        from app.graph.factories import make_minimax_llm_json
        from app.services.knowledge import KnowledgePipeline

        try:
            # Reuses the exact ingest extraction path so manual + automatic extraction stay identical.
            # Web sync path: cap at the request timeout (60s), not the digest ceiling (180s) —
            # this blocking call runs in the web process (web_concurrency=2).
            await KnowledgePipeline(
                self.db,
                GeminiEmbedder(),
                make_minimax_llm_json(),
                call_timeout=get_settings().active_llm_request_timeout,
            ).extract_product_features(doc, [])
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(f"feature extraction failed: {exc}") from exc
        await record_audit(
            self.db,
            action="extract_project_features",
            actor_id=admin.id,
            target_type="project",
            target_id=str(project_id),
        )
        return await self.list_features(project_id)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        return await require_project(self.db, project_id)
