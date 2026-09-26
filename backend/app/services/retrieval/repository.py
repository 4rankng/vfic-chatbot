"""Retrieval facade for the agent layer: one port, four focused repositories.

This is the class the graph injects as its read-only retrieval port
(:class:`app.graph.ports.GraphRetrievalPort`). It adds no behavior of its own —
it binds one db session (plus the optional multi-Page Facebook project scope)
to the four repositories that own the actual queries:

- :mod:`.document_repository` — memory match + hybrid document retrieval.
- :mod:`.faq_repository` — the canonical chunk-based FAQ read arms.
- :mod:`.catalog_repository` — project/persona catalog + job features, and the
  default ``RecommendationQueryPort`` implementation.
- :mod:`.timetable_repository` — bus timetable reads.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return
SQLAlchemy Row lists/scalars exactly as the inline ``db.execute(...).all()``
calls did.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.project.external_api import (
    ExternalApiOutcome,
    ExternalApiPromptEntry,
    ProjectExternalApiService,
    parse_config,
)
from app.services.retrieval.catalog_repository import CatalogRepository, RecommendationQueries
from app.services.retrieval.document_repository import DocumentRepository
from app.services.retrieval.faq_repository import FaqRepository
from app.services.retrieval.timetable_repository import TimetableRepository

logger = logging.getLogger(__name__)


class RetrievalRepository:
    """Read-only retrieval queries backing the agent's tools + prompt assembly.

    Class-level aliases below keep the historical test and call sites working:
    the floors and predicates are defined on the repository that owns them.
    """

    SIMILARITY_FLOOR = DocumentRepository.SIMILARITY_FLOOR
    FAQ_SIMILARITY_FLOOR = FaqRepository.FAQ_SIMILARITY_FLOOR
    _LEXICAL_STOPWORDS = DocumentRepository._LEXICAL_STOPWORDS

    _ann_enabled = staticmethod(DocumentRepository._ann_enabled)
    _chunk_visibility = staticmethod(DocumentRepository._chunk_visibility)

    def __init__(
        self,
        db: AsyncSession,
        *,
        page_project_ids: tuple[str, ...] | None = None,
        recommendation: object | None = None,
    ) -> None:
        self.db = db
        # Page-scoped catalog for multi-Page Facebook: when set, the Project
        # catalog surfaces (active_project_ids, active_projects_with_card,
        # list_active_projects, project_id_by_slug, income_summary_for_active_projects,
        # recommend_jobs_for_lead/list_active_jobs) are restricted to the Facebook
        # Page's assigned Project set. None → deployment-wide (Zalo + legacy).
        self.page_project_ids: tuple[str, ...] | None = (
            tuple(page_project_ids) if page_project_ids is not None else None
        )
        self._documents = DocumentRepository(db)
        self._faq = FaqRepository(db)
        self._catalog = CatalogRepository(db, page_project_ids=self.page_project_ids)
        self._timetable = TimetableRepository(db)
        # The recruitment query seam: any object satisfying the recruitment
        # context's RecommendationQueryPort may be injected; the default adapter
        # owns the lead resolution and page scoping.
        self._recommendation: object = (
            recommendation
            if recommendation is not None
            else RecommendationQueries(db, page_project_ids=self.page_project_ids)
        )

    @property
    def last_match_degraded(self) -> str | None:
        """Degradation reason from the most recent ``match_documents`` call."""
        return self._documents.last_match_degraded

    async def match_memories(self, emb: str, top_k: int, filter_json: str) -> list:
        return await self._documents.match_memories(emb, top_k, filter_json)

    async def match_documents(
        self,
        emb: str,
        top_k: int,
        filter_json: str,
        *,
        project_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list:
        return await self._documents.match_documents(
            emb,
            top_k,
            filter_json,
            project_ids=project_ids,
            query_text=query_text,
        )

    async def match_faq(
        self,
        emb: str,
        top_k: int = 3,
        *,
        filter_json: str = "{}",
        project_ids: list[str] | None = None,
        floor: float | None = None,
    ) -> list:
        return await self._faq.match_faq(
            emb,
            top_k,
            filter_json=filter_json,
            project_ids=project_ids,
            floor=floor,
        )

    async def match_faq_lexical(
        self,
        query: str,
        *,
        top_k: int = 5,
        project_ids: list[str] | None = None,
        filter_json: str = "{}",
        threshold: float = 0.30,
    ) -> list:
        return await self._faq.match_faq_lexical(
            query,
            top_k=top_k,
            project_ids=project_ids,
            filter_json=filter_json,
            threshold=threshold,
        )

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False):
        return await self._catalog.project_id_by_slug(slug, active_only=active_only)

    async def list_active_projects(self) -> list:
        return await self._catalog.list_active_projects()

    async def active_projects_with_card(self) -> list:
        return await self._catalog.active_projects_with_card()

    async def active_persona_body(self, provider: str | None = None) -> str | None:
        return await self._catalog.active_persona_body(provider)

    async def active_project_ids(self) -> list[str]:
        return await self._catalog.active_project_ids()

    async def project_ids_for_page(self, account_key: str) -> list[str]:
        return await self._catalog.project_ids_for_page(account_key)

    async def search_bus_timetable(self, company: str, question: str, limit: int) -> list:
        return await self._timetable.search_bus_timetable(company, question, limit)

    async def job_features_for_project(self, project_id) -> list:
        return await self._catalog.job_features_for_project(project_id)

    async def project_external_api_catalog(self, project_slug: str | None) -> list[Any]:
        """Prompt-ready guide for the configured external API in scope.

        At most one entry: the resolved project's admin-written guide. Best-effort
        — an unreadable row or a failed query yields ``[]`` (the prompt block is
        then simply absent) so a turn never breaks because of an admin
        integration.
        """
        try:
            if project_slug:
                row = await self._catalog.external_api_project(project_slug)
                rows = [row] if row is not None else []
            else:
                rows = await self._catalog.projects_with_external_api()
        except Exception as exc:  # noqa: BLE001 — prompt injection must not break a turn
            logger.warning(
                "project external api guide read failed error_type=%s", type(exc).__name__
            )
            return []
        entries: list[Any] = []
        for row in rows:
            config = parse_config(row.external_api)
            if not config.enabled or not config.guide.strip():
                continue
            entries.append(
                ExternalApiPromptEntry(
                    slug=str(row.slug), name=str(row.name), guide=config.guide
                )
            )
        return entries

    async def call_project_external_api(
        self,
        *,
        project_slug: str | None,
        method: str,
        path: str,
        params: dict | None,
    ) -> ExternalApiOutcome:
        """Resolve the project, then make exactly one call through its integration.

        Project scope: an explicit slug wins; otherwise the only configured
        project is used, several configured projects are reported as
        ``ambiguous`` (the tool asks the candidate which one), and none is
        ``not_configured``.
        """
        requested_path = (path or "").strip()
        if project_slug:
            row = await self._catalog.external_api_project(project_slug)
            rows = [row] if row is not None else []
            if not rows:
                return ExternalApiOutcome("not_configured", None, requested_path, None, "")
        else:
            rows = await self._catalog.projects_with_external_api()
            if not rows:
                return ExternalApiOutcome("not_configured", None, requested_path, None, "")
            if len(rows) > 1:
                labels = ", ".join(str(candidate.name) for candidate in rows)
                return ExternalApiOutcome(
                    "ambiguous", None, requested_path, None, "", labels
                )
        row = rows[0]
        service = ProjectExternalApiService(self.db)
        runtime = await service.runtime(row.id)
        if runtime is None:
            return ExternalApiOutcome("not_configured", str(row.name), requested_path, None, "")
        config, api_key = runtime
        outcome = await service.invoke(
            row.id, config, api_key, method=method, path=requested_path, params=params
        )
        return outcome._replace(project_label=str(row.name))

    async def income_summary_for_active_projects(self):
        return await self._catalog.income_summary_for_active_projects()

    async def recommend_jobs_for_lead(
        self, chat_id: str, *, top_k: int = 5, province: str | None = None
    ):
        return await self._recommendation.recommend_jobs_for_lead(  # type: ignore[attr-defined]
            chat_id, top_k=top_k, province=province
        )

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
        return await self._recommendation.list_active_jobs(  # type: ignore[attr-defined]
            project_slug=project_slug,
            role=role,
            company=company,
            location=location,
            top_k=top_k,
            sort_by=sort_by,
        )


__all__ = ["RetrievalRepository"]
