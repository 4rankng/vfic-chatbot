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
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import User
from app.schemas.projects import (
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureReadiness,
    FeatureUpdate,
    IngestState,
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
from app.shared.domain.errors import ConflictError, NotFoundError
from app.services.geo.project_address import refresh_from_address
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.project.faq import ProjectFaqService
from app.services.project.features import ProjectFeatureService
from app.services.project.knowledge_export import ProjectKnowledgeExport, export_project_knowledge
from app.services.project.single_page_external_sources import SinglePageExternalSourceService
from app.services.project.repository import ProjectRepository, require_project
from app.services.knowledge.base_service import KnowledgeBaseService
from app.project_knowledge.domain.project import (
    ProjectActivationFacts,
    project_activation_error,
)

logger = logging.getLogger(__name__)

# A RAG project's discovery card is DERIVED from its active categories: the
# category projection rewrites summary/roles/location on every activation but
# only seeds the keys it preserves (category_projections applies them with
# setdefault). A discovery-card patch on a RAG project may therefore carry only
# the preserved keys — patching a derived one would promise a recruiter an edit
# the next activation silently discards.
_PROJECTION_PRESERVED_CARD_KEYS = frozenset({"highlights", "eligibility"})


def _mode_of(
    modes: dict[uuid.UUID, KnowledgeBaseMode], key: uuid.UUID | None
) -> KnowledgeBaseMode | None:
    """Look up one knowledge-base mode; a Project's nullable FK reads as None."""
    return modes.get(key) if key is not None else None


_REVISION_INGEST_STATE: dict[str, IngestState] = {
    "STAGED": "ingesting",
    "PROCESSING": "ingesting",
    "FAILED": "error",
    "ACTIVE": "ready",
    # ARCHIVED/CLEARED revisions never count
}

_DOCUMENT_INGEST_STATE: dict[str, IngestState] = {
    "UPLOADED": "ingesting",
    "PROCESSING": "ingesting",
    "FAILED": "error",
    "PUBLISHED": "ready",
    # ARCHIVED documents never count
}

def _freshness_key(ts: datetime | None) -> tuple[bool, datetime | None]:
    """Order artifacts by freshness; unstamped rows sort oldest but tie together."""
    return (ts is not None, ts)


async def _ingest_states_by_project(
    db: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, IngestState]:
    """Batched knowledge-ingest state per project — one query per source, no N+1.

    Sources: each knowledge category's latest revision (``MAX(revision_no)`` per
    category) and the project's knowledge documents. Unmapped statuses never
    count. The badge describes ingest state now, not history: any in-flight
    artifact is ``ingesting``; otherwise a failed latest category revision is
    ``error`` until that category is repaired or cleared. A newer successful
    sibling or source document cannot repair it. For documents, the freshest
    artifact (``freshest_at``, the newest of the row's timestamps) decides, so a
    document failure superseded by later successes is history. Equal-freshness
    newest rows count any failure as ``error``. Any
    remaining artifact is ``ready``. Projects with no counting rows are absent
    from the result (caller reads missing as None).
    """
    if not project_ids:
        return {}
    ids = [str(pid) for pid in project_ids]
    revision_rows = (
        await db.execute(
            text(
                "SELECT kc.project_id AS project_id, kcr.status::text AS status, "
                "GREATEST(kcr.created_at, kcr.activated_at) AS freshest_at "
                "FROM ( "
                "    SELECT r.category_id AS category_id, MAX(r.revision_no) AS revision_no "
                "    FROM knowledge_category_revisions r "
                "    JOIN knowledge_categories c ON c.id = r.category_id "
                "    WHERE c.project_id = ANY(:ids) "
                "    GROUP BY r.category_id "
                ") latest "
                "JOIN knowledge_category_revisions kcr "
                "  ON kcr.category_id = latest.category_id "
                " AND kcr.revision_no = latest.revision_no "
                "JOIN knowledge_categories kc ON kc.id = kcr.category_id "
                "WHERE kcr.quality_result->>'project_training_document_id' IS NULL"
            ),
            {"ids": ids},
        )
    ).all()
    document_rows = (
        await db.execute(
            text(
                "SELECT kd.project_id AS project_id, kd.status::text AS status, "
                "GREATEST(kd.created_at, kd.updated_at) AS freshest_at "
                "FROM knowledge_documents kd "
                "WHERE kd.project_id = ANY(:ids) "
                "AND kd.metadata->>'project_training_document_id' IS NULL"
            ),
            {"ids": ids},
        )
    ).all()
    failed_category_projects = {
        row.project_id for row in revision_rows if row.status == "FAILED"
    }
    artifacts: dict[uuid.UUID, list[tuple[IngestState, datetime | None]]] = {}
    for rows, mapping in (
        (revision_rows, _REVISION_INGEST_STATE),
        (document_rows, _DOCUMENT_INGEST_STATE),
    ):
        for row in rows:
            state = mapping.get(row.status)
            if state is None:
                continue
            artifacts.setdefault(row.project_id, []).append((state, row.freshest_at))
    states: dict[uuid.UUID, IngestState] = {}
    for project_id, rows in artifacts.items():
        if any(state == "ingesting" for state, _ts in rows):
            states[project_id] = "ingesting"
            continue
        if project_id in failed_category_projects:
            states[project_id] = "error"
            continue
        newest = max(_freshness_key(ts) for _state, ts in rows)
        if any(state == "error" and _freshness_key(ts) == newest for state, ts in rows):
            states[project_id] = "error"
        else:
            states[project_id] = "ready"
    return states


def _enqueue_direct_context_index(
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    text_blob: str,
) -> None:
    from app.composition.project_knowledge_jobs import (
        build_project_knowledge_direct_context_jobs,
    )

    build_project_knowledge_direct_context_jobs().index_direct_context(
        knowledge_base_id,
        project_id,
        text_blob,
    )


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)
        self.faqs = ProjectFaqService(self.db)
        self.features = ProjectFeatureService(self.db)
        self.single_page_external_sources = SinglePageExternalSourceService(self.db)

    async def export_knowledge(self, project_id: uuid.UUID) -> ProjectKnowledgeExport:
        return await export_project_knowledge(self.db, project_id)

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
        """List projects with per-project feature readiness and ingest state attached.

        Batched aggregates only — no N+1: one ``readiness_by_project`` query plus
        one ingest-state query per knowledge source. The catalog total is the
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
        ingest = await _ingest_states_by_project(self.db, [p.id for p in rows])
        modes = await self._knowledge_modes([p.knowledge_base_id for p in rows])
        out: list[ProjectOut] = []
        for p in rows:
            o = ProjectOut.model_validate(p)
            o.knowledge_mode = _mode_of(modes, p.knowledge_base_id)
            o.knowledge_document_count = doc_counts.get(p.id, 0)
            o.feature_readiness = FeatureReadiness(ready=ready.get(p.id, 0), total=total)
            o.ingest_state = ingest.get(p.id)
            out.append(o)
        return out, row_total

    async def get(self, project_id: uuid.UUID) -> Project:
        return await self._require_project(project_id)

    async def get_with_readiness(self, project_id: uuid.UUID) -> ProjectOut:
        """Single-project get with feature readiness and ingest state attached."""
        proj = await self._require_project(project_id)
        repo = JobFeatureValueRepo(self.db)
        ready = await repo.readiness_by_project([proj.id])
        total = await repo.active_catalog_size()
        doc_counts = await self.repo.knowledge_document_counts([proj.id])
        ingest = await _ingest_states_by_project(self.db, [proj.id])
        o = ProjectOut.model_validate(proj)
        o.knowledge_mode = _mode_of(
            await self._knowledge_modes([proj.knowledge_base_id]),
            proj.knowledge_base_id,
        )
        o.knowledge_document_count = doc_counts.get(proj.id, 0)
        o.feature_readiness = FeatureReadiness(ready=ready.get(proj.id, 0), total=total)
        o.ingest_state = ingest.get(proj.id)
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
            # A new project has no legacy card to protect, so category authority
            # owns its data from birth and the very first activation projects.
            category_authority_started=True,
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
        if body.is_active:
            await self._require_activation_ready(proj)
        if body.name is not None:
            proj.name = body.name.strip()
        if body.is_active is not None:
            proj.is_active = body.is_active
        if body.aliases is not None:
            proj.aliases = [value.strip() for value in body.aliases if value.strip()]
        if "discovery_card" in body.model_fields_set:
            mode = _mode_of(
                await self._knowledge_modes([proj.knowledge_base_id]),
                proj.knowledge_base_id,
            )
            patch = body.discovery_card
            if mode is not KnowledgeBaseMode.DIRECT_CONTEXT and not (
                patch and set(patch) <= _PROJECTION_PRESERVED_CARD_KEYS
            ):
                raise ConflictError("RAG discovery cards are derived from active categories")
            if not patch:
                raise ConflictError("Single-page Projects require a discovery card")
            # MERGE, never replace: the patch body carries only the keys its
            # caller owns (the brief chain sends `highlights` alone), and a
            # replace would wipe the projection-built summary/roles/location
            # on the next re-ingest.
            proj.index_card = {**(proj.index_card or {}), **patch}
            if "summary" in patch:
                proj.summary = patch["summary"]
            proj.discovery_revision += 1
            # Geo-distance side effect: the admin-authored card carries the
            # location a candidate would read. ``refresh_from_address`` defers to
            # the pipeline's grounded value and never raises, so the PATCH stays
            # independent of the geocoder (and adds no LLM call).
            await refresh_from_address(
                self.db, proj.id, str(proj.index_card.get("location") or "")
            )
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
        # Index DIRECT_CONTEXT text into knowledge_chunks so it participates in
        # cross-project retrieval (otherwise it is only reachable via FOCUSED-turn
        # system-prompt injection). Best-effort: the enqueue swallows Redis errors so a
        # transient queue failure never rolls back this publish.
        text_blob = getattr(direct_file, "normalized_text", None) or getattr(
            direct_file, "raw_text", None
        )
        if text_blob:
            _enqueue_direct_context_index(knowledge_base.id, project_id, text_blob)
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
        return {row[0]: row[1] for row in rows}

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
        # Training uploads and publication share this lock. The newest source
        # cannot change between this readiness check and the update's commit.
        # Read the database flag rather than a possibly stale ORM identity.
        already_active = await self.db.scalar(
            select(Project.is_active).where(Project.id == project.id).with_for_update()
        )
        if already_active is None:
            raise NotFoundError("project not found")
        if not already_active:
            source = await self.db.scalar(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.project_id == project.id,
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                    KnowledgeDocument.metadata_["project_training"].as_string().is_not(None),
                )
                .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if source is not None and (
                source.status != KnowledgeStatus.PUBLISHED
                or (source.digest_meta or {}).get("project_training", {}).get("status")
                != "COMPLETED"
            ):
                raise ConflictError(
                    "Tệp thông tin dự án chưa được xử lý xong. "
                    "Vui lòng kiểm tra hoặc thử xử lý lại trước khi bật tuyển dụng."
                )
        modes = await self._knowledge_modes([project.knowledge_base_id])
        mode = _mode_of(modes, project.knowledge_base_id)
        if mode is KnowledgeBaseMode.DIRECT_CONTEXT:
            preflight = ProjectActivationFacts(
                knowledge_mode=mode.value,
                has_discovery_card=bool(project.index_card),
                has_direct_file=True,
            )
            if error := project_activation_error(preflight):
                raise ConflictError(error)
            direct_file = await self.db.scalar(
                select(KnowledgeBaseDirectFile.id).where(
                    KnowledgeBaseDirectFile.knowledge_base_id == project.knowledge_base_id
                )
            )
            facts = ProjectActivationFacts(
                knowledge_mode=mode.value,
                has_discovery_card=bool(project.index_card),
                has_direct_file=direct_file is not None,
            )
        elif mode is KnowledgeBaseMode.RAG:
            facts = ProjectActivationFacts(knowledge_mode=mode.value)
        else:
            facts = ProjectActivationFacts(knowledge_mode=None)
        if error := project_activation_error(facts):
            raise ConflictError(error)
