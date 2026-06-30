"""Project ("product catalog") business logic: CRUD + master-index rebuild + worker
product-feature CRUD/re-extraction.

Extracted from the projects router so the router stays a thin HTTP layer. Project CRUD +
reindex use the ORM; the worker product-feature read/edit uses raw SQL (a join over
``job_feature_values`` + ``worker_feature_catalog`` the ORM can't express cleanly) — that
SQL is encapsulated here rather than in the router. (Phase 5 will push it behind a
repository.)

Raises ``HTTPException`` for not-found / conflict / LLM-failure outcomes (behavior-
preserving vs. the legacy router).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
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
from app.services.knowledge import sync_project_highlights
from app.services.knowledge.repository import JobFeatureValueRepo

logger = logging.getLogger(__name__)

def _feature_from_row(r: Any) -> FeatureOut:
    return FeatureOut(
        id=r.id,
        project_id=r.project_id,
        feature_id=r.feature_id,
        feature_key=r.feature_key,
        name_vi=r.name_vi,
        category=r.category,
        worker_question_vi=r.worker_question_vi,
        value_text=r.value_text,
        value_json=r.value_json or {},
        strength_score=float(r.strength_score),
        display_priority=r.display_priority,
        is_highlight=r.is_highlight,
        is_missing=r.is_missing,
        needs_clarification=r.needs_clarification,
        evidence_text=r.evidence_text,
        source_document_id=r.source_document_id,
        updated_at=r.updated_at,
    )


def _faq_answer_from_content(content: str | None, question: str) -> str:
    text_value = (content or "").strip()
    prefix = f"FAQ: {question}".strip()
    if prefix and text_value.startswith(prefix):
        text_value = text_value[len(prefix):].strip()
    return text_value or (content or "")


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, is_active: bool | None = None) -> list[Project]:
        q = select(Project).order_by(Project.created_at.desc())
        if is_active is not None:
            q = q.where(Project.is_active == is_active)
        return list((await self.db.scalars(q)).all())

    async def list_with_readiness(
        self, is_active: bool | None = None
    ) -> list[ProjectOut]:
        """List projects with per-project feature readiness attached.

        One batched ``readiness_by_project`` query — no N+1. The catalog total is the
        active-feature count.
        """
        rows = await self.list(is_active)
        repo = JobFeatureValueRepo(self.db)
        ready = await repo.readiness_by_project([p.id for p in rows])
        total = await repo.active_catalog_size()
        doc_counts = await self._knowledge_document_counts([p.id for p in rows])
        out: list[ProjectOut] = []
        for p in rows:
            o = ProjectOut.model_validate(p)
            o.knowledge_document_count = doc_counts.get(p.id, 0)
            o.feature_readiness = FeatureReadiness(
                ready=ready.get(p.id, 0), total=total
            )
            out.append(o)
        return out

    async def get(self, project_id: uuid.UUID) -> Project:
        return await self._require_project(project_id)

    async def get_with_readiness(self, project_id: uuid.UUID) -> ProjectOut:
        """Single-project get with feature readiness attached."""
        proj = await self._require_project(project_id)
        repo = JobFeatureValueRepo(self.db)
        ready = await repo.readiness_by_project([proj.id])
        total = await repo.active_catalog_size()
        doc_counts = await self._knowledge_document_counts([proj.id])
        o = ProjectOut.model_validate(proj)
        o.knowledge_document_count = doc_counts.get(proj.id, 0)
        o.feature_readiness = FeatureReadiness(
            ready=ready.get(proj.id, 0), total=total
        )
        return o

    async def _knowledge_document_counts(
        self, project_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not project_ids:
            return {}
        rows = (
            await self.db.execute(
                select(KnowledgeDocument.project_id, func.count(KnowledgeDocument.id))
                .where(
                    KnowledgeDocument.project_id.in_(project_ids),
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                )
                .group_by(KnowledgeDocument.project_id)
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows if row[0] is not None}

    async def create(self, body: ProjectCreate, admin: User) -> Project:
        name = body.name.strip()
        existing = (
            await self.db.scalars(
                select(Project)
                .where(func.lower(func.trim(Project.name)) == name.lower())
                .order_by(Project.created_at.asc())
                .limit(1)
            )
        ).first()
        if existing is not None:
            return existing

        proj = Project(slug=body.slug.strip(), name=name, is_active=body.is_active)
        self.db.add(proj)
        try:
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001 — unique slug violation etc.
            await self.db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"project create failed: {exc}") from exc
        await record_audit(
            self.db, action="create_project", actor_id=admin.id, target_type="project", target_id=str(proj.id)
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
                raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
            if body.default_persona_id is not None:
                persona = await self.db.get(Persona, body.default_persona_id)
                if persona is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
            proj.default_persona_id = body.default_persona_id
        await record_audit(
            self.db, action="update_project", actor_id=actor.id, target_type="project", target_id=str(proj.id)
        )
        await self.db.commit()
        await self.db.refresh(proj)
        return proj

    async def delete(self, project_id: uuid.UUID, admin: User) -> None:
        proj = await self._require_project(project_id)
        await record_audit(
            self.db, action="delete_project", actor_id=admin.id, target_type="project", target_id=str(proj.id)
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
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"index rebuild failed: {exc}") from exc
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
        total = int(
            (
                await self.db.execute(
                    text("SELECT count(*) FROM bus_routes WHERE project_id = :pid"),
                    {"pid": str(project_id)},
                )
            ).scalar()
            or 0
        )
        if total == 0:
            return BusTimetableResponse(data=[], total=0, page=page, per_page=per_page)

        route_rows = (
            await self.db.execute(
                text(
                    "SELECT id, route_name, route_no, route_variant, shift, direction, "
                    "       area, mode, source_page, notes "
                    "FROM bus_routes "
                    "WHERE project_id = :pid "
                    "ORDER BY route_name ASC, shift ASC, direction ASC, route_variant ASC "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"pid": str(project_id), "limit": per_page, "offset": (page - 1) * per_page},
            )
        ).mappings().all()
        if not route_rows:
            return BusTimetableResponse(data=[], total=total, page=page, per_page=per_page)

        route_ids = [str(row["id"]) for row in route_rows]
        stop_rows = (
            await self.db.execute(
                text(
                    "SELECT id, route_id, stop_order, stop_name, "
                    "       to_char(scheduled_time, 'HH24:MI') AS scheduled_time "
                    "FROM bus_stops "
                    "WHERE route_id = ANY(CAST(:route_ids AS uuid[])) "
                    "ORDER BY route_id, stop_order"
                ),
                {"route_ids": route_ids},
            )
        ).mappings().all()
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
        rows = (
            await self.db.execute(
                text(
                    "SELECT kc.id, kc.content, kc.questions, "
                    "       kc.metadata ->> 'source_anchor' AS source_anchor, kd.file_name "
                    "FROM knowledge_chunks kc "
                    "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                    "WHERE kd.project_id = :pid "
                    "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                    "  AND kc.category = 'faq' "
                    "ORDER BY kc.created_at DESC, kc.chunk_index ASC "
                    "LIMIT :limit"
                ),
                {"pid": str(project_id), "limit": limit},
            )
        ).mappings().all()
        data = [
            ProjectFaqOut(
                id=row["id"],
                question=(row["questions"] or ["FAQ"])[0],
                answer=_faq_answer_from_content(
                    row["content"], (row["questions"] or ["FAQ"])[0]
                ),
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
            raise HTTPException(status.HTTP_404_NOT_FOUND, "feature value not found")

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
        doc = (
            await self.db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.project_id == project_id, KnowledgeDocument.raw_text.is_not(None))
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(1)
            )
        ).first()
        if doc is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "no source document with text for this project — upload a posting first",
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
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"feature extraction failed: {exc}") from exc
        await record_audit(
            self.db, action="extract_project_features", actor_id=admin.id, target_type="project", target_id=str(project_id)
        )
        return await self.list_features(project_id)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        proj = await self.db.get(Project, project_id)
        if proj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
        return proj
