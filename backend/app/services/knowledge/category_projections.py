"""Deterministic Project projections for RAG knowledge categories.

The revision lifecycle in ``category_service`` (staging, activation, cutover,
rollback) composes a :class:`CategoryProjectionWriter` instead of owning the
Job / BusRoute / BusStop writes inline: the lifecycle decides WHEN projections
run (post-cutover activation, cutover rebuild, a rollback restore, or an
explicit clear), the writer decides HOW rows change. The seam lets activation
tests supply a recording adapter instead of a live database.
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
from app.schemas.knowledge_categories import CategoryDocument, KnowledgeCategoryKey
from app.shared.domain.errors import NotFoundError
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    get_category_definition,
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
        for record in getattr(document, definition.list_field):
            job_ids = getattr(record, "job_ids", None)
            if job_ids is None:
                continue
            targets = _target_jobs(jobs, job_ids)
            if key is KnowledgeCategoryKey.COMPENSATION:
                for job in targets:
                    job.salary_min = record.estimated_income_min_vnd or record.base_salary_vnd
                    job.salary_max = record.estimated_income_max_vnd or record.base_salary_vnd
            elif key is KnowledgeCategoryKey.REQUIREMENTS:
                for job in targets:
                    job.age_min = record.age_min
                    job.age_max = record.age_max
                    job.gender_requirement = ", ".join(record.genders) or None
                    job.experience_required = record.experience
                    job.requirements = _record_text(record)
            elif key is KnowledgeCategoryKey.WORK_SCHEDULES:
                for job in targets:
                    job.shift = _record_text(record)
            elif key is KnowledgeCategoryKey.BENEFITS:
                for job in targets:
                    job.benefits = "\n".join(
                        value for value in (job.benefits, record.name, record.description) if value
                    )
            elif key is KnowledgeCategoryKey.ACCOMMODATION:
                for job in targets:
                    job.accommodation_support = record.available
            elif key is KnowledgeCategoryKey.MEALS:
                for job in targets:
                    job.meal_support = record.provided
            elif key is KnowledgeCategoryKey.TRANSPORTATION:
                for job in targets:
                    job.transport_support = True

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
        for sibling in siblings:
            sibling_revision = await self.db.get(
                KnowledgeCategoryRevision,
                sibling.active_revision_id,
            )
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
                    source_page="category_yaml",
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
        project = await self.db.get(Project, project_id)
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
                existing.vacancy_count = item.vacancies or 1
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
                        vacancy_count=item.vacancies or 1,
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
        project.is_active = bool(roles)

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
                project.index_card = {}
                project.discovery_revision += 1
                project.is_active = False
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


def _target_jobs(jobs: list[Job], job_ids: list[str]) -> list[Job]:
    if not job_ids:
        return jobs
    allowed = set(job_ids)
    return [job for job in jobs if job.stable_key in allowed]


def _record_text(record: object) -> str:
    payload = record.model_dump(mode="json", exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _bus_shift(value: str | None) -> str:
    normalized = (value or "").casefold()
    if "night" in normalized or "đêm" in normalized or "dem" in normalized:
        return "night"
    if "admin" in normalized or "hành chính" in normalized or "hanh chinh" in normalized:
        return "admin"
    return "day"
