"""Retrieval facade for the agent layer: one port, four focused repositories.

This is the class the graph injects as its read-only retrieval port
(:class:`app.graph.ports.GraphRetrievalPort`). It binds one db session and
enforces the optional multi-Page Facebook project scope before delegating
to the four repositories that own the actual queries:

- :mod:`.document_repository` — memory match + hybrid document retrieval.
- :mod:`.faq_repository` — the canonical chunk-based FAQ read arms.
- :mod:`.catalog_repository` — project/persona catalog + job features, and the
  rich active-project fit catalog.
- :mod:`.timetable_repository` — bus timetable reads.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return
SQLAlchemy Row lists/scalars exactly as the inline ``db.execute(...).all()``
calls did.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.external_api_core import ExternalApiOutcome
from app.services.geo.geocoding import geocode
from app.services.retrieval.catalog_repository import CatalogRepository
from app.services.retrieval.document_repository import DocumentRepository
from app.services.retrieval.faq_repository import FaqRepository
from app.services.retrieval.timetable_repository import TimetableRepository
from app.services.tingting_api import TingtingApiService, TingtingFlowStore, TingtingVerifyAttemptsStore

logger = logging.getLogger(__name__)


class RetrievalRepository:
    """Read-only retrieval queries backing the agent's tools + prompt assembly.

    Class-level aliases below keep the historical test and call sites working:
    the floors and predicates are defined on the repository that owns them.
    """

    SIMILARITY_FLOOR = DocumentRepository.SIMILARITY_FLOOR
    FAQ_SIMILARITY_FLOOR = FaqRepository.FAQ_SIMILARITY_FLOOR

    _ann_enabled = staticmethod(DocumentRepository._ann_enabled)
    _chunk_visibility = staticmethod(DocumentRepository._chunk_visibility)

    def __init__(
        self,
        db: AsyncSession,
        *,
        page_project_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.db = db
        # Page-scoped catalog for multi-Page Facebook: when set, the Project
        # catalog surfaces (active_project_ids, active_projects_with_card,
        # list_active_projects, project_id_by_slug, income_summary_for_active_projects)
        # are restricted to the Facebook Page's assigned Project set. None →
        # deployment-wide (Zalo + legacy).
        self.page_project_ids: tuple[str, ...] | None = (
            tuple(page_project_ids) if page_project_ids is not None else None
        )
        self._documents = DocumentRepository(db)
        self._faq = FaqRepository(db)
        self._catalog = CatalogRepository(db, page_project_ids=self.page_project_ids)
        self._timetable = TimetableRepository(db)

    @property
    def last_match_degraded(self) -> str | None:
        """Degradation reason from the most recent ``match_documents`` call."""
        return self._documents.last_match_degraded

    def _knowledge_project_scope(self, requested: list[str] | None) -> list[str] | None:
        """Intersect caller scope with the channel assignment; [] always denies reads."""
        if self.page_project_ids is None:
            return requested
        assigned = set(self.page_project_ids)
        if requested is None:
            return sorted(assigned)
        return sorted(assigned.intersection(requested))

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
            project_ids=self._knowledge_project_scope(project_ids),
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
            project_ids=self._knowledge_project_scope(project_ids),
            floor=floor,
        )

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False):
        return await self._catalog.project_id_by_slug(slug, active_only=active_only)

    async def load_category_knowledge(self, project_ids: list[str], category_key: str) -> list:
        return await self._catalog.load_category_knowledge(project_ids, category_key)

    async def list_active_projects(self) -> list:
        return await self._catalog.list_active_projects()

    async def geocode_area(self, query: str) -> tuple[float, float] | None:
        """Resolve a candidate's stated area to ``(lat, lng)`` for distance evidence.

        Delegates to the cached, throttled, fail-open geocoding client
        (``app.services.geo.geocoding``): it never raises, so a geocoder outage
        degrades the catalog answer to its pre-distance form instead of failing
        the turn. Two quality guards ride along:

        * the search is biased toward the box the active projects live in
          (``CatalogRepository.active_area_viewbox``) — a bare landmark name is
          otherwise resolved nationwide and can land hundreds of km from every
          project it is supposed to rank against. Bias, never a hard box — a
          candidate whose area is genuinely outside the region must still
          resolve, so the distances stay truthful.
        * the admin-configured Google credential (settings page / env) enables
          a regional hop before Nominatim, for the landmarks OSM lacks.
        """
        # Inline import: the integration-settings facade pulls the audit and
        # model graph; a module-level import risks an import cycle.
        from app.services.integration_settings import IntegrationSettingsService

        viewbox = await self._catalog.active_area_viewbox()
        providers = await IntegrationSettingsService(self.db).resolve_geocoder()
        return await geocode(query, viewbox=viewbox, providers=providers)

    async def estimate_distances_km(
        self,
        origin: tuple[float, float],
        destinations: list[tuple[float, float]],
    ) -> list[tuple[float, float | None] | None]:
        """Road estimates via the matrix providers, served from the DB cache.

        Same fail-open contract as :meth:`geocode_area`: the service never
        raises, so a provider/config failure degrades the numbers to ``None``
        entries and the tool falls back to straight-line distance instead of
        failing the turn. Keys follow the same integration settings as the
        geocoder ladder (admin page / env).
        """
        # Inline import: same cycle-avoidance reasoning as geocode_area above.
        from app.services.integration_settings import IntegrationSettingsService

        from app.services.geo.distance import estimate_distances

        providers = await IntegrationSettingsService(self.db).resolve_geocoder()
        return await estimate_distances(origin, destinations, providers=providers)

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

    async def tingting_api_configured(self) -> bool:
        """Whether the deployment-wide TingTing integration has a usable key.

        The prompt gate for the embedded reset guide: with no key the model gets
        no endpoint instructions, so it cannot promise a reset it cannot perform.
        """
        return await TingtingApiService(self.db).configured()

    async def call_tingting_api(
        self,
        *,
        method: str,
        path: str,
        params: dict | None,
    ) -> ExternalApiOutcome:
        """Perform exactly one call against the TingTing reset API.

        Configuration is read per call (one primary-key SELECT): an admin who
        rotates the key sees it take effect on the next turn.
        """
        service = TingtingApiService(self.db)
        try:
            runtime = await service.runtime()
        except Exception as exc:  # noqa: BLE001 — a config read must not 500 a turn
            logger.warning(
                "tingting api runtime read failed error_type=%s", type(exc).__name__
            )
            runtime = None
        return await service.invoke(runtime, method=method, path=path, params=params)

    async def tingting_flow_state(self, phone: str) -> dict:
        """The stored reset-flow state for a phone (empty when none/expired)."""
        return await TingtingFlowStore().load(phone)

    async def save_tingting_flow_state(self, phone: str, state: dict) -> dict:
        """Merge one step's state into the phone's flow key."""
        return await TingtingFlowStore().save(phone, state)

    async def clear_tingting_flow_state(self, phone: str) -> None:
        """Drop the flow state once the password has been reset."""
        await TingtingFlowStore().clear(phone)

    async def tingting_verify_attempts(self, scope: str) -> int:
        """Failed verification tries spent in this conversation so far."""
        return await TingtingVerifyAttemptsStore().count(scope)

    async def record_tingting_verify_failure(self, scope: str) -> int:
        """Count one failed verification; returns the running total."""
        return await TingtingVerifyAttemptsStore().record_failure(scope)

    async def clear_tingting_verify_attempts(self, scope: str) -> None:
        """Clear the counter once identity verification has succeeded."""
        await TingtingVerifyAttemptsStore().reset(scope)

    async def tingting_reset_oa_id(self) -> str:
        """The OA account key the reset flow is pinned to (``""`` = any OA)."""
        try:
            return await TingtingApiService(self.db).reset_oa_id()
        except Exception as exc:  # noqa: BLE001 — a config read must not 500 a turn
            logger.warning("tingting reset scope read failed error_type=%s", type(exc).__name__)
            return ""

    async def tingting_hotline(self) -> str:
        """The admin-editable escalation hotline (``""`` = unset/cleared).

        Read fresh every support-OA turn so an admin edit takes effect on the
        next message. The empty read is flagged here — the one turn-time site —
        because the Alembic seed guarantees a value: an empty row means an
        admin cleared the field or the seed never ran, and the reply building
        degrades to the honest no-number form instead of a code fallback.
        """
        try:
            hotline = await TingtingApiService(self.db).hotline()
        except Exception as exc:  # noqa: BLE001 — a config read must not 500 a turn
            logger.warning("tingting hotline read failed error_type=%s", type(exc).__name__)
            return ""
        if not hotline:
            logger.warning("tingting hotline setting is empty; escalation reply omits the number")
        return hotline

    async def income_summary_for_active_projects(self):
        return await self._catalog.income_summary_for_active_projects()


__all__ = ["RetrievalRepository"]
