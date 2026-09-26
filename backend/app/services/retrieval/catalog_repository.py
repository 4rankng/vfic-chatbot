"""Project-catalog, persona, and recruitment-feature reads for the agent.

The catalog owns the Page-scoped project surfaces (slug resolution, active
project listings, the master-index card set) plus the per-project job-feature
rows. The recommendation adapter below is the default implementation of the
recruitment context's ``RecommendationQueryPort`` for this seam: the retrieval
facade may instead be handed any object satisfying that port, which keeps the
graph-injected read surface from instantiating recruitment repositories
inside method bodies.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lead.repository import LeadRepository
from app.services.recommendation import (
    ActiveJobLookup,
    LeadJobRecommendation,
    LeadProfile,
    RecommendationRepository,
)

logger = logging.getLogger(__name__)


class CatalogRepository:
    """Read-only project/persona catalog queries, optionally Page-scoped."""

    def __init__(self, db: AsyncSession, *, page_project_ids: tuple[str, ...] | None) -> None:
        self.db = db
        # Page-scoped catalog for multi-Page Facebook: when set, the Project
        # catalog surfaces (active_project_ids, active_projects_with_card,
        # list_active_projects, project_id_by_slug, income_summary_for_active_projects)
        # are restricted to the Facebook Page's assigned Project set. None →
        # deployment-wide (Zalo + legacy).
        self.page_project_ids: tuple[str, ...] | None = page_project_ids

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False) -> uuid.UUID | None:
        """Resolve a project id from its (unique) slug; optionally require ``is_active``."""
        sql = (
            "SELECT p.id FROM projects p "
            "WHERE p.slug = :s AND p.knowledge_base_id IS NOT NULL"
        )
        if active_only:
            sql += " AND p.is_active"
        pid = (await self.db.execute(text(sql), {"s": slug})).scalar_one_or_none()
        if pid is None:
            return None
        if self.page_project_ids is not None and str(pid) not in self.page_project_ids:
            return None
        return pid

    async def list_active_projects(self) -> list:
        """name/slug/summary of active projects (catalog tool)."""
        if self.page_project_ids is not None:
            return (
                await self.db.execute(
                    text(
                        "SELECT p.name, p.slug, p.summary FROM projects p "
                        "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL "
                        "AND p.id = ANY(CAST(:pids AS uuid[])) ORDER BY p.name"
                    ),
                    {"pids": list(self.page_project_ids)},
                )
            ).all()
        return (
            await self.db.execute(
                text(
                    "SELECT p.name, p.slug, p.summary FROM projects p "
                    "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL ORDER BY p.name"
                )
            )
        ).all()

    async def active_projects_with_card(self) -> list:
        """Active projects for the master-index prompt."""
        if self.page_project_ids is not None:
            return (
                await self.db.execute(
                    text(
                        "SELECT p.name, p.slug, p.summary, p.index_card, p.aliases "
                        "FROM projects p "
                        "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL "
                        "AND p.id = ANY(CAST(:pids AS uuid[])) ORDER BY p.name"
                    ),
                    {"pids": list(self.page_project_ids)},
                )
            ).all()
        return (
            await self.db.execute(
                text(
                    "SELECT p.name, p.slug, p.summary, p.index_card, p.aliases "
                    "FROM projects p "
                    "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL ORDER BY p.name"
                )
            )
        ).all()

    async def external_api_project(self, slug: str) -> Any | None:
        """One active, externally-integrated project resolved by slug.

        The ``external_api`` payload travels with the row so the caller can
        project the endpoint catalog without a second read. Page scope applies
        exactly as it does for :meth:`list_active_projects`.
        """
        sql = (
            "SELECT p.id, p.slug, p.name, p.external_api FROM projects p "
            "WHERE p.slug = :s AND p.is_active AND p.external_api IS NOT NULL "
            "AND p.external_api->>'enabled' = 'true'"
        )
        if self.page_project_ids is not None:
            sql += " AND p.id = ANY(CAST(:pids AS uuid[]))"
            return (
                await self.db.execute(
                    text(sql), {"s": slug, "pids": list(self.page_project_ids)}
                )
            ).first()
        return (await self.db.execute(text(sql), {"s": slug})).first()

    async def projects_with_external_api(self) -> list:
        """Every active, externally-integrated project, Page-scoped."""
        sql = (
            "SELECT p.id, p.slug, p.name, p.external_api FROM projects p "
            "WHERE p.is_active AND p.external_api IS NOT NULL "
            "AND p.external_api->>'enabled' = 'true'"
        )
        if self.page_project_ids is not None:
            sql += " AND p.id = ANY(CAST(:pids AS uuid[])) ORDER BY p.name"
            return (
                await self.db.execute(text(sql), {"pids": list(self.page_project_ids)})
            ).all()
        return (await self.db.execute(text(sql + " ORDER BY p.name"))).all()

    async def active_persona_body(self, provider: str | None = None) -> str | None:
        """Return the effective persona body for ``provider``, or None."""
        if provider:
            return (
                await self.db.execute(
                    text(
                        """
                        SELECT pe.body_md
                        FROM personas AS pe
                        WHERE pe.id = COALESCE(
                            (
                                SELECT apa.persona_id
                                FROM adapter_persona_assignments AS apa
                                WHERE apa.provider = :provider
                            ),
                            (
                                SELECT active.id
                                FROM personas AS active
                                WHERE active.is_active
                                ORDER BY active.updated_at DESC
                                LIMIT 1
                            )
                        )
                        """
                    ),
                    {"provider": provider},
                )
            ).scalar_one_or_none()
        return (
            await self.db.execute(
                text(
                    "SELECT body_md FROM personas "
                    "WHERE is_active ORDER BY updated_at DESC LIMIT 1"
                )
            )
        ).scalar_one_or_none()

    async def active_project_ids(self) -> list[str]:
        """Active KB-backed project ids: the Page's assigned set when scoped
        for multi-Page Facebook, else the deployment-wide catalog."""
        if self.page_project_ids is not None:
            return list(self.page_project_ids)
        rows = await self.db.scalars(
            text(
                "SELECT p.id::text FROM projects p "
                "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL "
                "ORDER BY p.id"
            )
        )
        return list(rows)

    async def project_ids_for_page(self, account_key: str) -> list[str]:
        """Assigned Project ids for one channel account (e.g. a Facebook Page).

        Returns the raw assignment set (no ``is_active`` filter): catalog
        queries apply their own active filters, and the activation gate counts
        only ACTIVE-project mappings. Used by the graph layer to bind a
        conversation's Page scope onto the retrieval port.
        """
        from app.models.channel_account import ChannelAccount, ChannelAccountProject

        rows = (
            await self.db.execute(
                select(ChannelAccountProject.project_id)
                .join(
                    ChannelAccount,
                    ChannelAccount.id == ChannelAccountProject.channel_account_id,
                )
                .where(ChannelAccount.account_key == account_key)
                .order_by(ChannelAccountProject.created_at.asc())
            )
        ).scalars()
        return [str(pid) for pid in rows]

    async def job_features_for_project(self, project_id: uuid.UUID) -> list:
        """A project's active worker features in catalog display order.

        Filtered to ``is_active`` catalog rows so disabled criteria (migration 0009) are
        hidden from the agent tool and readiness gauge without re-extraction.
        """
        return (
            await self.db.execute(
                text(
                    "SELECT jfv.value_text, jfv.value_json, jfv.is_highlight, jfv.is_missing, "
                    "       jfv.needs_clarification, jfv.evidence_text, "
                    "       wfc.name_vi, wfc.feature_key "
                    "FROM job_feature_values jfv "
                    "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                    "WHERE jfv.project_id = :pid AND wfc.is_active = true "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()

    async def income_summary_for_active_projects(self):
        """Verbatim income evidence for active projects (Page-scoped when bound)."""
        scope = list(self.page_project_ids) if self.page_project_ids is not None else None
        return await RecommendationRepository(self.db).income_summary_for_active_projects(scope)


class RecommendationQueries:
    """Default ``RecommendationQueryPort`` implementation for the retrieval seam.

    Resolves the lead once, builds the typed profile, and delegates matching
    to the recommendation repository. A caller injecting its own port replaces
    this whole object; the page-scope contract then belongs to the injector
    (the port signatures carry no scope argument).
    """

    def __init__(self, db: AsyncSession, *, page_project_ids: tuple[str, ...] | None) -> None:
        self.db = db
        self.page_project_ids = page_project_ids

    async def recommend_jobs_for_lead(
        self, chat_id: str, *, top_k: int = 5, province: str | None = None
    ):
        """Return a typed profile-based job recommendation outcome."""
        try:
            lead = await LeadRepository(self.db).by_zalo_id(chat_id)
            profile = LeadProfile.from_lead(lead)
        except Exception:
            logger.warning("lead lookup failed for chat_id=%s", chat_id, exc_info=True)
            return LeadJobRecommendation("unavailable")
        if not profile.has_any_signal:
            return LeadJobRecommendation("insufficient_profile")
        try:
            page_project_ids = (
                list(self.page_project_ids) if self.page_project_ids is not None else None
            )
            jobs = await RecommendationRepository(self.db).match_jobs(
                profile, top_k=top_k, province=province, project_ids=page_project_ids
            )
        except Exception:
            logger.warning("recommendation lookup failed for chat_id=%s", chat_id, exc_info=True)
            return LeadJobRecommendation("unavailable")
        if not jobs:
            return LeadJobRecommendation("no_match")
        return LeadJobRecommendation("matched", tuple(jobs))

    async def list_active_jobs(
        self,
        *,
        project_slug: str | None = None,
        role: str | None = None,
        company: str | None = None,
        location: str | None = None,
        top_k: int = 3,
        sort_by: str | None = None,
    ):
        """List structured vacancies within the active Agent knowledge base."""
        catalog = CatalogRepository(self.db, page_project_ids=self.page_project_ids)
        try:
            if project_slug:
                project_id = await catalog.project_id_by_slug(project_slug, active_only=True)
                project_ids = [str(project_id)] if project_id is not None else []
            else:
                project_ids = await catalog.active_project_ids()
        except Exception:
            logger.warning("active-project lookup failed for vacancy catalog", exc_info=True)
            return ActiveJobLookup("unavailable")
        return await RecommendationRepository(self.db).list_active_jobs(
            role=role,
            company=company,
            location=location,
            top_k=top_k,
            project_ids=project_ids,
            sort_by=sort_by,  # type: ignore[arg-type]
        )
