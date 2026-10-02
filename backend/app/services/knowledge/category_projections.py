"""Deterministic Project projections for RAG knowledge categories.

The revision lifecycle in ``category_service`` (staging, activation) and the
authority transitions in ``category_authority`` (cutover, rollback) compose a
:class:`CategoryProjectionWriter` instead of owning the Job / BusRoute / BusStop
writes inline: the lifecycle decides WHEN projections run (post-cutover
activation, cutover rebuild, a rollback restore, or an explicit clear), the
writer decides HOW rows change. The seam lets activation tests supply a
recording adapter instead of a live database.

:func:`render_category_units` is the other half of a revision's projection — the
embedder input units an activation embeds and stores as chunks.
"""

from __future__ import annotations

import json
import uuid
from datetime import time
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bus import BusRoute, BusStop
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.schemas.knowledge_categories import (
    CategoryDocument,
    JobsDocument,
    KnowledgeCategoryKey,
    StrictModel,
    TransportationDocument,
)
from app.shared.domain.errors import NotFoundError
from app.project_knowledge.domain.category import shared_project_category_value
from app.project_knowledge.domain.category_catalog import (
    CATEGORY_DEFINITIONS,
    get_category_definition,
)
from app.services.geo.project_address import refresh_from_address
from app.services.knowledge.category_contracts import (
    validate_category_payload,
)


class CategoryProjectionWriter(Protocol):
    """Writes Project-visible projections for a category revision.

    Implemented by :class:`SqlAlchemyCategoryProjectionWriter`; a recording
    adapter can stand in for tests that must not touch projection rows.
    """

    async def apply_for_revision(
        self,
        project_id: uuid.UUID,
        revision: KnowledgeCategoryRevision,
        document: CategoryDocument,
    ) -> None: ...

    async def clear(
        self,
        project_id: uuid.UUID,
        key: KnowledgeCategoryKey,
    ) -> None: ...

    async def delete_all(self, project_id: uuid.UUID) -> None: ...

    async def rebuild(
        self,
        project_id: uuid.UUID,
        categories: list[KnowledgeCategory],
    ) -> None: ...


def render_category_units(document: CategoryDocument) -> list[dict]:
    """Build the embedder input units (content + chunk metadata) for a document."""
    definition = get_category_definition(document.category)
    units: list[dict] = []
    for record in getattr(document, definition.list_field):
        payload = record.model_dump(mode="json", exclude_none=True)
        stable_id = str(payload.get("id"))
        # FaqItem carries per-item tags (section / sub-category from the source
        # sheet). Pop them out of the generic field dump so they do not appear
        # as a mid-payload JSON array in arbitrary field order, then re-attach
        # as a deterministic trailing "Tags:" line in the embedder input. The
        # parser already emits tags in a stable order (broad section → specific
        # sub-category); that order is preserved as-is, not re-sorted. Other
        # categories have no ``tags`` field, so the pop is a harmless no-op.
        tags = payload.pop("tags", [])
        content = f"{definition.label_vi}\n" + "\n".join(
            f"{field}: {json.dumps(value, ensure_ascii=False)}"
            for field, value in payload.items()
        )
        if tags:
            content += f"\nTags: {', '.join(tags)}"
        unit = {
            "content": content,
            "source_quote": content,
            "summary": str(payload.get("title") or payload.get("name") or "") or None,
            "questions": [],
            "entities": {"stable_id": stable_id},
            "metadata": {
                "category": document.category.value,
                "stable_id": stable_id,
            },
        }
        if document.category is KnowledgeCategoryKey.JOBS:
            unit["entities"]["job_title"] = payload.get("title")
        if document.category is KnowledgeCategoryKey.FAQ:
            unit["questions"] = [payload["question"], *payload.get("question_variants", [])]
            unit["required_terms"] = payload.get("required_terms", [])
            unit["forbidden_terms"] = payload.get("forbidden_terms", [])
            # Mirror tags into chunk metadata — same chunk_metadata.tags shape
            # canonical.to_unit uses — so a future pgvector metadata-filter
            # consumer can target them. No consumer reads this today.
            unit["metadata"]["chunk_metadata"] = {"tags": tags}
        units.append(unit)
    return units


class SqlAlchemyCategoryProjectionWriter:
    """Mirrors validated category payloads into Job / BusRoute / BusStop rows."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
    async def apply_for_revision(
        self,
        project_id: uuid.UUID,
        revision: KnowledgeCategoryRevision,
        document: CategoryDocument,
    ) -> None:
        key = KnowledgeCategoryKey(document.category)
        if key is KnowledgeCategoryKey.JOBS:
            await self._replace_jobs(project_id, revision, document)
            await self._reapply_active_sibling_projections(project_id)
            return
        await self.clear(project_id, key)
        await self._apply_projection_records(project_id, document, revision)

    async def _apply_projection_records(
        self,
        project_id: uuid.UUID,
        document: CategoryDocument,
        revision: KnowledgeCategoryRevision,
    ) -> None:
        key = KnowledgeCategoryKey(document.category)
        if key is KnowledgeCategoryKey.TRANSPORTATION:
            await self._replace_transportation_routes(project_id, revision, document)
        jobs = await self._derived_jobs(project_id)
        definition = get_category_definition(key)
        records = getattr(document, definition.list_field)
        # A project can describe multiple conditions in its KB. Only facts
        # shared by every record are safe to copy into a role's scalar fields;
        # the complete records remain available to retrieval for explanation.
        for job in jobs:
            if key is KnowledgeCategoryKey.COMPENSATION:
                job.salary_min = shared_project_category_value([
                    record.estimated_income_min_vnd
                    if record.estimated_income_min_vnd is not None
                    else record.base_salary_vnd
                    for record in records
                ])
                job.salary_max = shared_project_category_value([
                    record.estimated_income_max_vnd
                    if record.estimated_income_max_vnd is not None
                    else record.base_salary_vnd
                    for record in records
                ])
            elif key is KnowledgeCategoryKey.REQUIREMENTS:
                job.age_min = shared_project_category_value([record.age_min for record in records])
                job.age_max = shared_project_category_value([record.age_max for record in records])
                job.gender_requirement = shared_project_category_value([
                    ", ".join(record.genders) or None for record in records
                ])
                job.experience_required = shared_project_category_value([
                    record.experience for record in records
                ])
                job.requirements = "\n".join(_record_text(record) for record in records) or None
            elif key is KnowledgeCategoryKey.WORK_SCHEDULES:
                job.shift = "\n".join(_record_text(record) for record in records) or None
            elif key is KnowledgeCategoryKey.BENEFITS:
                job.benefits = "\n".join(
                    value for record in records
                    for value in (record.name, record.description) if value
                ) or None
            elif key is KnowledgeCategoryKey.ACCOMMODATION:
                job.accommodation_support = shared_project_category_value([
                    record.available for record in records
                ])
            elif key is KnowledgeCategoryKey.MEALS:
                job.meal_support = shared_project_category_value([record.provided for record in records])
            elif key is KnowledgeCategoryKey.TRANSPORTATION:
                job.transport_support = bool(records) or None

    async def _reapply_active_sibling_projections(self, project_id: uuid.UUID) -> None:
        """Rebuild derived Job fields after Jobs rows are recreated.

        Active category pointers remain authoritative across a Jobs replacement,
        so their projections must be replayed in the same transaction.
        """
        siblings = (
            await self.db.scalars(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project_id,
                    KnowledgeCategory.category_key != KnowledgeCategoryKey.JOBS.value,
                    KnowledgeCategory.active_revision_id.is_not(None),
                )
            )
        ).all()
        revision_ids = [sibling.active_revision_id for sibling in siblings]
        revisions_by_id: dict[uuid.UUID, KnowledgeCategoryRevision] = {}
        if revision_ids:
            revisions_by_id = {
                revision.id: revision
                for revision in (
                    await self.db.scalars(
                        select(KnowledgeCategoryRevision).where(
                            KnowledgeCategoryRevision.id.in_(revision_ids)
                        )
                    )
                ).all()
            }
        for sibling in siblings:
            revision_id = sibling.active_revision_id
            if revision_id is None:
                continue
            sibling_revision = revisions_by_id.get(revision_id)
            if sibling_revision is None:
                continue
            sibling_document = validate_category_payload(
                sibling.category_key,
                sibling_revision.normalized_payload,
            )
            await self._apply_projection_records(
                project_id,
                sibling_document,
                sibling_revision,
            )

    async def _replace_transportation_routes(
        self,
        project_id: uuid.UUID,
        revision: KnowledgeCategoryRevision,
        document: CategoryDocument,
    ) -> None:
        if not isinstance(document, TransportationDocument):
            raise ValueError("Transportation projection requires its category document")
        await self.db.execute(
            delete(BusRoute).where(
                BusRoute.project_id == project_id,
                BusRoute.source_category_revision_id.is_not(None),
            )
        )
        company = await self.db.scalar(
            select(Company).where(Company.project_id == project_id).order_by(Company.id)
        )
        if company is None:
            project = await self.db.get(Project, project_id)
            if project is None:
                raise NotFoundError("Project not found")
            company = Company(project_id=project_id, name=project.name, aliases=project.aliases)
            self.db.add(company)
            await self.db.flush()
        for record in document.transportation:
            directions = (
                ("outbound", "return")
                if record.direction == "round_trip"
                else (("outbound",) if record.direction == "to_factory" else ("return",))
            )
            for direction in directions:
                route = BusRoute(
                    project_id=project_id,
                    company_id=company.id,
                    source_category_revision_id=revision.id,
                    route_name=record.name,
                    route_no=record.id,
                    route_variant=record.id,
                    shift=_bus_shift(record.shift),
                    direction=direction,
                    mode="company_bus",
                    source_page="category_markdown",
                    notes=record.notes,
                    metadata_={
                        "service_days": record.service_days,
                        "fee_vnd": record.fee_vnd,
                        "yaml_direction": record.direction,
                    },
                    route_group_key=record.id,
                )
                self.db.add(route)
                await self.db.flush()
                stops = record.stops if direction == "outbound" else list(reversed(record.stops))
                for index, stop in enumerate(stops, start=1):
                    self.db.add(
                        BusStop(
                            route_id=route.id,
                            stop_order=index,
                            stop_name=stop.name,
                            scheduled_time=time.fromisoformat(stop.time) if stop.time else None,
                            raw_stop_text=stop.address,
                        )
                    )

    async def _replace_jobs(
        self,
        project_id: uuid.UUID,
        revision: KnowledgeCategoryRevision,
        document: CategoryDocument,
    ) -> None:
        if not isinstance(document, JobsDocument):
            raise ValueError("Jobs projection requires its category document")
        project = await self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        companies = list(
            (
                await self.db.scalars(
                    select(Company).where(Company.project_id == project_id).order_by(Company.id)
                )
            ).all()
        )
        company = companies[0] if companies else None
        if company is None:
            company = Company(project_id=project_id, name=project.name, aliases=project.aliases)
            self.db.add(company)
            await self.db.flush()
            companies = [company]
        # --- KB-authoritative job sync with manual-job protection ---
        # Policy:
        #   1. Only touch jobs where source_category_revision_id IS NOT NULL
        #      (KB-derived). Manually created jobs (NULL) are never touched.
        #   2. Preserve the status of jobs marked FULL, EXPIRED, or ARCHIVED —
        #      a re-learn must never reactivate a closed/full/expired position.
        #   3. Upsert by stable_key: if the job already exists with a terminal
        #      status, update its fields but keep the status. If it's new, create
        #      it as ACTIVE.
        existing_jobs: dict[str, Job] = {}
        if company:
            existing_jobs = {
                j.stable_key: j
                for j in (
                    await self.db.scalars(
                        select(Job).where(
                            Job.company_id == company.id,
                            Job.source_category_revision_id.is_not(None),
                            Job.stable_key.is_not(None),
                        )
                    )
                ).all()
                if j.stable_key is not None
            }

        # Terminal statuses that must be preserved across re-learns.
        _TERMINAL_STATUSES = {JobStatus.FULL, JobStatus.EXPIRED, JobStatus.ARCHIVED}

        # Keys present in the new KB revision.
        new_keys: set[str] = set()

        roles: list[str] = []
        locations: list[str] = []
        for item in document.jobs:
            roles.append(item.title)
            if item.location:
                locations.append(item.location)
            new_keys.add(item.id)
            existing = existing_jobs.get(item.id)
            if existing is not None:
                # Upsert: update mutable fields, preserve terminal status.
                existing.title = item.title
                existing.factory_name = company.name
                existing.province = item.location
                existing.address = item.location
                # Vacancy counts belong to Job management, not project KB.
                existing.description = item.summary
                existing.source_category_revision_id = revision.id
                # Only set ACTIVE if the job isn't in a terminal state.
                if existing.status not in _TERMINAL_STATUSES:
                    existing.status = JobStatus.ACTIVE
            else:
                self.db.add(
                    Job(
                        company_id=company.id,
                        stable_key=item.id,
                        source_category_revision_id=revision.id,
                        title=item.title,
                        factory_name=company.name,
                        province=item.location,
                        address=item.location,
                        status=JobStatus.ACTIVE,
                        description=item.summary,
                    )
                )
        card = dict(project.index_card or {})
        location = ", ".join(dict.fromkeys(locations))
        role_text = ", ".join(dict.fromkeys(roles[:3]))
        summary = (
            f"{project.name} đang tuyển {role_text} tại {location}."
            if role_text and location
            else f"{project.name} đang tuyển {role_text}."
            if role_text
            else f"Dự án tuyển dụng {project.name}."
        )
        card.update(
            {
                "summary": summary,
                "roles": roles,
                "location": location,
            }
        )
        card.setdefault("eligibility", [])
        card.setdefault("highlights", [])
        project.index_card = card
        project.summary = summary
        project.discovery_revision += 1
        # Geo-distance side effect: these jobs records carry the recruiter's own
        # location string, so geocode it here. ``refresh_from_address`` defers to
        # the pipeline's grounded value and never raises — activating a category
        # must not depend on the geocoder.
        await refresh_from_address(self.db, project_id, location)

    async def clear(
        self,
        project_id: uuid.UUID,
        key: KnowledgeCategoryKey,
    ) -> None:
        jobs = await self._derived_jobs(project_id)
        if key is KnowledgeCategoryKey.JOBS:
            company_ids = list(
                await self.db.scalars(select(Company.id).where(Company.project_id == project_id))
            )
            if company_ids:
                await self.db.execute(
                    delete(Job).where(
                        Job.company_id.in_(company_ids),
                        Job.source_category_revision_id.is_not(None),
                    )
                )
            project = await self.db.get(Project, project_id)
            if project is not None:
                card = dict(project.index_card or {})
                card.pop("roles", None)
                project.index_card = card
                project.discovery_revision += 1
        elif key is KnowledgeCategoryKey.COMPENSATION:
            for job in jobs:
                job.salary_min = None
                job.salary_max = None
        elif key is KnowledgeCategoryKey.REQUIREMENTS:
            for job in jobs:
                job.age_min = None
                job.age_max = None
                job.gender_requirement = None
                job.experience_required = None
                job.requirements = None
        elif key is KnowledgeCategoryKey.WORK_SCHEDULES:
            for job in jobs:
                job.shift = None
        elif key is KnowledgeCategoryKey.BENEFITS:
            for job in jobs:
                job.benefits = None
        elif key is KnowledgeCategoryKey.ACCOMMODATION:
            for job in jobs:
                job.accommodation_support = None
        elif key is KnowledgeCategoryKey.MEALS:
            for job in jobs:
                job.meal_support = None
        elif key is KnowledgeCategoryKey.TRANSPORTATION:
            for job in jobs:
                job.transport_support = None
            await self.db.execute(
                delete(BusRoute).where(
                    BusRoute.project_id == project_id,
                    BusRoute.source_category_revision_id.is_not(None),
                )
            )

    async def delete_all(self, project_id: uuid.UUID) -> None:
        await self.db.execute(
            delete(BusRoute).where(
                BusRoute.project_id == project_id,
                BusRoute.source_category_revision_id.is_not(None),
            )
        )
        company_ids = list(
            await self.db.scalars(select(Company.id).where(Company.project_id == project_id))
        )
        if company_ids:
            await self.db.execute(
                delete(Job).where(
                    Job.company_id.in_(company_ids),
                    Job.source_category_revision_id.is_not(None),
                )
            )

    async def rebuild(
        self,
        project_id: uuid.UUID,
        categories: list[KnowledgeCategory],
    ) -> None:
        await self.delete_all(project_id)
        by_key = {category.category_key: category for category in categories}
        jobs_category = by_key.get(KnowledgeCategoryKey.JOBS.value)
        if jobs_category is not None and jobs_category.active_revision_id is not None:
            jobs_revision = await self.db.get(
                KnowledgeCategoryRevision,
                jobs_category.active_revision_id,
            )
            if jobs_revision is not None:
                jobs_document = validate_category_payload(
                    KnowledgeCategoryKey.JOBS,
                    jobs_revision.normalized_payload,
                )
                await self._replace_jobs(project_id, jobs_revision, jobs_document)
        for definition in CATEGORY_DEFINITIONS:
            if definition.key is KnowledgeCategoryKey.JOBS:
                continue
            category = by_key.get(definition.key.value)
            if category is None or category.active_revision_id is None:
                continue
            revision = await self.db.get(
                KnowledgeCategoryRevision,
                category.active_revision_id,
            )
            if revision is None:
                continue
            document = validate_category_payload(
                definition.key,
                revision.normalized_payload,
            )
            await self._apply_projection_records(project_id, document, revision)

    async def _derived_jobs(self, project_id: uuid.UUID) -> list[Job]:
        return list(
            (
                await self.db.scalars(
                    select(Job)
                    .join(Company, Company.id == Job.company_id)
                    .where(
                        Company.project_id == project_id,
                        Job.source_category_revision_id.is_not(None),
                    )
                )
            ).all()
        )




def _record_text(record: StrictModel) -> str:
    payload = record.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _bus_shift(value: str | None) -> str:
    normalized = (value or "").casefold()
    if "night" in normalized or "đêm" in normalized or "dem" in normalized:
        return "night"
    if "admin" in normalized or "hành chính" in normalized or "hanh chinh" in normalized:
        return "admin"
    return "day"
