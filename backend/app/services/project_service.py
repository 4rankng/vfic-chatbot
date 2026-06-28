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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.projects import (
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
    ProjectCreate,
    ProjectUpdate,
)
from app.services.audit_service import record_audit
from app.services.knowledge import sync_project_highlights

logger = logging.getLogger(__name__)

_FEATURE_COLUMNS = (
    "jfv.id, jfv.project_id, jfv.feature_id, jfv.value_text, jfv.value_json, "
    "jfv.strength_score, jfv.display_priority, jfv.is_highlight, jfv.is_missing, "
    "jfv.needs_clarification, jfv.evidence_text, jfv.source_document_id, jfv.updated_at, "
    "wfc.feature_key, wfc.name_vi, wfc.category, wfc.worker_question_vi"
)
_FEATURE_FROM = "job_feature_values jfv JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id"


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


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, is_active: bool | None = None) -> list[Project]:
        q = select(Project).order_by(Project.created_at.desc())
        if is_active is not None:
            q = q.where(Project.is_active == is_active)
        return list((await self.db.scalars(q)).all())

    async def get(self, project_id: uuid.UUID) -> Project:
        return await self._require_project(project_id)

    async def create(self, body: ProjectCreate, admin: User) -> Project:
        proj = Project(slug=body.slug.strip(), name=body.name.strip(), is_active=body.is_active)
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

    async def update(self, project_id: uuid.UUID, body: ProjectUpdate, admin: User) -> Project:
        proj = await self._require_project(project_id)
        if body.name is not None:
            proj.name = body.name.strip()
        if body.is_active is not None:
            proj.is_active = body.is_active
        if body.default_persona_id is not None:
            proj.default_persona_id = body.default_persona_id
        await record_audit(
            self.db, action="update_project", actor_id=admin.id, target_type="project", target_id=str(proj.id)
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
        from app.graph.clients import GeminiEmbedder
        from app.graph.factories import make_minimax_llm_json
        from app.services.knowledge import KnowledgePipeline

        try:
            await KnowledgePipeline(self.db, GeminiEmbedder(), make_minimax_llm_json()).build_project_index(proj.id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"index rebuild failed: {exc}") from exc
        await self.db.refresh(proj)
        return proj

    async def list_features(self, project_id: uuid.UUID) -> FeatureListResponse:
        """List the project's 16 extracted worker product features (catalog order)."""
        await self._require_project(project_id)
        rows = (
            await self.db.execute(
                text(
                    f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} "  # noqa: S608 — static f-string
                    "WHERE jfv.project_id = :pid "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()
        return FeatureListResponse(data=[_feature_from_row(r) for r in rows], total=len(rows))

    async def update_feature(
        self, project_id: uuid.UUID, feature_id: uuid.UUID, body: FeatureUpdate, admin: User
    ) -> FeatureOut:
        """Admin edit of one extracted feature value; re-syncs product highlights."""
        found = (
            await self.db.execute(
                text("SELECT 1 FROM job_feature_values WHERE id = :fid AND project_id = :pid"),
                {"fid": str(feature_id), "pid": str(project_id)},
            )
        ).first()
        if found is None:
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
            await self.db.execute(text(f"UPDATE job_feature_values SET {', '.join(sets)} WHERE id = :fid"), params)  # noqa: S608
            await record_audit(
                self.db,
                action="update_project_feature",
                actor_id=admin.id,
                target_type="job_feature_value",
                target_id=str(feature_id),
            )
            await self.db.commit()
            await sync_project_highlights(self.db, project_id)

        row = (
            await self.db.execute(
                text(f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} WHERE jfv.id = :fid"),  # noqa: S608
                {"fid": str(feature_id)},
            )
        ).first()
        assert row is not None  # noqa: S101 — just verified existence above
        return _feature_from_row(row)

    async def extract_features(self, project_id: uuid.UUID, admin: User) -> FeatureListResponse:
        """Synchronously re-extract the 16 product features from the project's latest posting.

        Persona-pattern: one blocking MiniMax call in the web process (~5-10s). Overwrites the
        project's 16 feature values. Requires a source document with extracted text.
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
        from app.graph.clients import GeminiEmbedder
        from app.graph.factories import make_minimax_llm_json
        from app.services.knowledge import KnowledgePipeline

        try:
            # Reuses the exact ingest extraction path so manual + automatic extraction stay identical.
            await KnowledgePipeline(self.db, GeminiEmbedder(), make_minimax_llm_json()).extract_product_features(doc, [])
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
