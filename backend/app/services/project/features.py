"""Project feature + bus-timetable catalog sub-service.

Extracted from :class:`ProjectService`: listing / editing / re-extracting the
project's worker product features, plus the structured bus-timetable catalog
read. The parent service composes this via thin delegates so the public
``ProjectService`` surface is unchanged.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.projects import (
    BusRouteOut,
    BusStopOut,
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
)
from app.services.audit_service import record_audit
from app.shared.domain.errors import ConflictError, NotFoundError, UpstreamError
from app.services.knowledge import sync_project_highlights
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.services.project.mapping import _feature_from_row
from app.services.project.repository import ProjectRepository, require_project
from app.project_knowledge.application.providers import KnowledgeProviderFactory


class ProjectFeatureService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        providers: KnowledgeProviderFactory | None = None,
    ) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)
        self._providers = providers

    def _provider_factory(self) -> KnowledgeProviderFactory:
        if self._providers is None:
            from app.composition.project_knowledge import build_knowledge_provider_factory

            self._providers = build_knowledge_provider_factory()
        return self._providers

    async def list_features(self, project_id: uuid.UUID) -> FeatureListResponse:
        """List the project's active extracted worker product features (catalog order)."""
        await require_project(self.db, project_id)
        rows = await JobFeatureValueRepo(self.db).list_for_project(project_id)
        return FeatureListResponse(data=[_feature_from_row(r) for r in rows], total=len(rows))

    async def list_bus_timetable(
        self, project_id: uuid.UUID, *, page: int = 1, per_page: int = 6
    ) -> BusTimetableResponse:
        """List one page of structured bus routes with ordered stops."""
        await require_project(self.db, project_id)
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
        await require_project(self.db, project_id)
        doc = await self.repo.get_latest_document_with_text(project_id)
        if doc is None:
            raise ConflictError(
                "no source document with text for this project — upload a posting first"
            )
        # Imported lazily (langchain/provider deps kept out of the web-process import path).
        from app.core.config import get_settings
        from app.services.integration_settings import IntegrationSettingsService
        from app.services.knowledge import KnowledgePipeline

        try:
            integration_settings = IntegrationSettingsService(self.db)
            minimax_config = await integration_settings.resolve_minimax()
            openrouter_config = await integration_settings.resolve_openrouter()
            # Reuses the exact ingest extraction path so manual + automatic extraction stay identical.
            # Web sync path: cap at the request timeout (60s), not the digest ceiling (180s) —
            # this blocking call runs in the web process (web_concurrency=2).
            await KnowledgePipeline(
                self.db,
                self._provider_factory().embedder(
                    openrouter_api_key=openrouter_config.api_key
                ),
                self._provider_factory().json_extractor(
                    minimax_api_key=minimax_config.api_key,
                    openrouter_api_key=openrouter_config.api_key,
                ),
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
