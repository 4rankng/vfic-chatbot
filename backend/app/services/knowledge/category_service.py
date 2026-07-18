"""Independent Project RAG-category lifecycle and deterministic projections."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, time
from typing import Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version, bump_kb_caches
from app.models.company import Company, Project
from app.models.bus import BusRoute, BusStop
from app.models.job import Job, JobStatus
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import User
from app.schemas.knowledge_categories import CategoryDocument, KnowledgeCategoryKey
from app.schemas.project_knowledge import CategoryCatalogItemOut, CategorySourceOut
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError, UpstreamError
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    canonical_category_json,
    category_checksum,
    get_category_definition,
    parse_category_yaml,
    validate_category_payload,
    validate_job_references,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo


class CategoryEmbedder(Protocol):
    async def batch(self, texts: list[str]) -> list[list[float]]: ...


class KnowledgeCategoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_catalog(self, project_id: uuid.UUID) -> list[CategoryCatalogItemOut]:
        await self._require_rag_project(project_id)
        categories = list(
            (
                await self.db.scalars(
                    select(KnowledgeCategory)
                    .where(KnowledgeCategory.project_id == project_id)
                    .order_by(KnowledgeCategory.created_at, KnowledgeCategory.category_key)
                )
            ).all()
        )
        active_ids = [row.active_revision_id for row in categories if row.active_revision_id]
        revisions = {
            row.id: row
            for row in (
                (
                    await self.db.scalars(
                        select(KnowledgeCategoryRevision).where(
                            KnowledgeCategoryRevision.id.in_(active_ids)
                        )
                    )
                ).all()
                if active_ids
                else []
            )
        }
        latest_by_category: dict[uuid.UUID, KnowledgeCategoryRevision] = {}
        if categories:
            latest_numbers = (
                select(
                    KnowledgeCategoryRevision.category_id,
                    func.max(KnowledgeCategoryRevision.revision_no).label("revision_no"),
                )
                .where(KnowledgeCategoryRevision.category_id.in_([row.id for row in categories]))
                .group_by(KnowledgeCategoryRevision.category_id)
                .subquery()
            )
            revision_rows = (
                await self.db.scalars(
                    select(KnowledgeCategoryRevision)
                    .join(
                        latest_numbers,
                        (latest_numbers.c.category_id == KnowledgeCategoryRevision.category_id)
                        & (
                            latest_numbers.c.revision_no
                            == KnowledgeCategoryRevision.revision_no
                        ),
                    )
                )
            ).all()
            for revision_row in revision_rows:
                latest_by_category.setdefault(revision_row.category_id, revision_row)
        rows_by_key = {row.category_key: row for row in categories}
        output: list[CategoryCatalogItemOut] = []
        for definition in CATEGORY_DEFINITIONS:
            category = rows_by_key.get(definition.key.value)
            revision = revisions.get(category.active_revision_id) if category else None
            latest = latest_by_category.get(category.id) if category else None
            output.append(
                CategoryCatalogItemOut(
                    key=definition.key,
                    label_vi=definition.label_vi,
                    active_revision_id=revision.id if revision else None,
                    active_revision_no=revision.revision_no if revision else None,
                    active_checksum=revision.content_sha256 if revision else None,
                    latest_revision_id=latest.id if latest else None,
                    latest_revision_no=latest.revision_no if latest else None,
                    status=latest.status if latest else None,
                    error_message=latest.error_message if latest else None,
                    updated_at=(latest.activated_at or latest.created_at if latest else category.updated_at)
                    if category
                    else None,
                )
            )
        return output

    async def stage_replacement(
        self,
        *,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
        filename: str,
        source_yaml: str,
        actor: User,
    ) -> tuple[KnowledgeCategoryRevision, str]:
        await self._require_rag_project(project_id)
        try:
            document = parse_category_yaml(category_key, source_yaml)
            await self._validate_active_job_references(project_id, document)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        category = await self._locked_category(project_id, category_key)
        latest = await self.db.scalar(
            select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                KnowledgeCategoryRevision.category_id == category.id
            )
        )
        revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=int(latest or 0) + 1,
            status=KnowledgeCategoryRevisionStatus.STAGED,
            source_filename=filename,
            source_yaml=source_yaml,
            normalized_payload=document.model_dump(mode="json"),
            content_sha256=category_checksum(document),
            created_by=actor.id,
        )
        self.db.add(revision)
        await self.db.flush()
        await record_audit(
            self.db,
            action="stage_project_knowledge_category",
            actor_id=actor.id,
            target_type="knowledge_category_revision",
            target_id=str(revision.id),
            payload={"project_id": str(project_id), "category": category_key.value},
        )
        await self.db.commit()
        await self.db.refresh(revision)

        from app.workers.category_worker import enqueue_category_revision

        try:
            job_id = enqueue_category_revision(revision.id)
        except Exception as exc:
            revision.status = KnowledgeCategoryRevisionStatus.FAILED
            revision.error_message = "The processing queue is unavailable"
            await self.db.commit()
            raise UpstreamError(
                "Could not queue the category update; the active content is unchanged"
            ) from exc
        return revision, job_id

    async def get_active_source(
        self,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
    ) -> CategorySourceOut:
        await self._require_rag_project(project_id)
        category = await self.db.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == category_key.value,
            )
        )
        if category is None or category.active_revision_id is None:
            raise NotFoundError("Knowledge category has no active content")
        revision = await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
        if revision is None:
            raise NotFoundError("Active knowledge category revision not found")
        definition = get_category_definition(category_key)
        return CategorySourceOut(
            key=category_key,
            label_vi=definition.label_vi,
            revision_id=revision.id,
            revision_no=revision.revision_no,
            filename=revision.source_filename,
            content=revision.source_yaml,
            checksum=revision.content_sha256,
            updated_at=revision.activated_at or revision.created_at,
        )

    async def activate_revision(
        self,
        revision_id: uuid.UUID,
        embedder: CategoryEmbedder,
        *,
        start_category_authority: bool = True,
    ) -> None:
        revision = await self.db.get(KnowledgeCategoryRevision, revision_id)
        if revision is None:
            raise NotFoundError("Category revision not found")
        if revision.status is KnowledgeCategoryRevisionStatus.ACTIVE:
            return
        category = await self.db.get(KnowledgeCategory, revision.category_id)
        if category is None:
            raise NotFoundError("Category not found")

        claim = await self.db.execute(
            update(KnowledgeCategoryRevision)
            .where(
                KnowledgeCategoryRevision.id == revision_id,
                KnowledgeCategoryRevision.status.in_(
                    [
                        KnowledgeCategoryRevisionStatus.STAGED,
                        KnowledgeCategoryRevisionStatus.FAILED,
                    ]
                ),
            )
            .values(
                status=KnowledgeCategoryRevisionStatus.PROCESSING,
                error_message=None,
            )
        )
        await self.db.commit()
        if claim.rowcount != 1:
            return

        try:
            document = validate_category_payload(
                category.category_key,
                revision.normalized_payload,
            )
            await self._validate_active_job_references(category.project_id, document)
            units = _render_units(document)
            vectors = await embedder.batch([unit["content"] for unit in units])
            if len(vectors) != len(units):
                raise RuntimeError("embedding provider returned an incomplete category batch")

            category = await self._locked_category(
                category.project_id,
                KnowledgeCategoryKey(category.category_key),
            )
            revision = await self.db.get(KnowledgeCategoryRevision, revision_id)
            if revision is None:
                raise NotFoundError("Category revision not found")
            latest_revision_no = await self.db.scalar(
                select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                    KnowledgeCategoryRevision.category_id == category.id
                )
            )
            if revision.revision_no < int(latest_revision_no or revision.revision_no):
                revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
                await self.db.commit()
                return
            old_revision = (
                await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
                if category.active_revision_id
                else None
            )
            knowledge_document = KnowledgeDocument(
                file_name=revision.source_filename,
                source="category_yaml",
                status=KnowledgeStatus.PUBLISHED,
                raw_text=revision.source_yaml,
                metadata_={
                    "schema_version": "category-1.0",
                    "category": category.category_key,
                    "category_revision_id": str(revision.id),
                },
                project_id=category.project_id,
                mime_type="application/yaml",
                stage="PUBLISHED",
                category_revision_id=revision.id,
            )
            self.db.add(knowledge_document)
            await self.db.flush()
            await KnowledgeChunkRepo(self.db).insert_category_revision(
                document_id=knowledge_document.id,
                project_id=category.project_id,
                category_revision_id=revision.id,
                category_key=category.category_key,
                units_with_vectors=list(zip(units, vectors, strict=True)),
            )
            await self._replace_projection(category.project_id, revision, document)
            project = await self.db.get(Project, category.project_id)
            if project is not None and start_category_authority:
                project.category_authority_started = True
            if old_revision is not None:
                old_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
            category.active_revision_id = revision.id
            category.updated_at = func.now()
            revision.status = KnowledgeCategoryRevisionStatus.ACTIVE
            revision.activated_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            failed = await self.db.get(KnowledgeCategoryRevision, revision_id)
            if failed is not None:
                failed.status = KnowledgeCategoryRevisionStatus.FAILED
                failed.error_message = f"{type(exc).__name__}: {exc}"[:1000]
                await self.db.commit()
            raise

        await bump_kb_caches()
        await bump_cache_version("jobs")

    async def clear(
        self,
        *,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
        actor: User,
    ) -> KnowledgeCategoryRevision:
        await self._require_rag_project(project_id)
        category = await self._locked_category(project_id, category_key)
        latest = await self.db.scalar(
            select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                KnowledgeCategoryRevision.category_id == category.id
            )
        )
        empty_payload = {
            "schema_version": "1.0",
            "category": category_key.value,
            get_category_definition(category_key).list_field: [],
        }
        empty_document = validate_category_payload(category_key, empty_payload, allow_empty=True)
        cleared = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=int(latest or 0) + 1,
            status=KnowledgeCategoryRevisionStatus.CLEARED,
            source_filename=f"{category_key.value}.yaml",
            source_yaml=canonical_category_json(empty_document),
            normalized_payload=empty_payload,
            content_sha256=category_checksum(empty_document),
            created_by=actor.id,
            activated_at=datetime.now(UTC),
        )
        self.db.add(cleared)
        old_revision = (
            await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
            if category.active_revision_id
            else None
        )
        if old_revision is not None:
            old_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
        await self._clear_projection(project_id, category_key)
        project = await self.db.get(Project, project_id)
        if project is not None:
            project.category_authority_started = True
        category.active_revision_id = None
        category.updated_at = func.now()
        await self.db.flush()
        await record_audit(
            self.db,
            action="clear_project_knowledge_category",
            actor_id=actor.id,
            target_type="knowledge_category",
            target_id=str(category.id),
            payload={"project_id": str(project_id), "category": category_key.value},
        )
        await self.db.commit()
        await self.db.refresh(cleared)
        await bump_kb_caches()
        await bump_cache_version("jobs")
        return cleared

    async def _require_rag_project(self, project_id: uuid.UUID) -> Project:
        project = await self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        knowledge_base = (
            await self.db.get(KnowledgeBase, project.knowledge_base_id)
            if project.knowledge_base_id
            else None
        )
        if knowledge_base is None or knowledge_base.mode is not KnowledgeBaseMode.RAG:
            raise ConflictError("This operation is available only for RAG Projects")
        return project

    async def _locked_category(
        self,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
    ) -> KnowledgeCategory:
        category = await self.db.scalar(
            select(KnowledgeCategory)
            .where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == category_key.value,
            )
            .with_for_update()
        )
        if category is None:
            raise NotFoundError("Knowledge category not found")
        return category

    async def _validate_active_job_references(
        self,
        project_id: uuid.UUID,
        document: CategoryDocument,
    ) -> None:
        if document.category is KnowledgeCategoryKey.JOBS:
            new_job_ids = {item.id for item in document.jobs}
            sibling_categories = (
                await self.db.scalars(
                    select(KnowledgeCategory).where(
                        KnowledgeCategory.project_id == project_id,
                        KnowledgeCategory.category_key != KnowledgeCategoryKey.JOBS.value,
                        KnowledgeCategory.active_revision_id.is_not(None),
                    )
                )
            ).all()
            for sibling in sibling_categories:
                revision = await self.db.get(
                    KnowledgeCategoryRevision,
                    sibling.active_revision_id,
                )
                if revision is None:
                    continue
                sibling_document = validate_category_payload(
                    sibling.category_key,
                    revision.normalized_payload,
                )
                validate_job_references(sibling_document, new_job_ids)
            return
        jobs_category = await self.db.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == KnowledgeCategoryKey.JOBS.value,
            )
        )
        known_ids: set[str] = set()
        if jobs_category and jobs_category.active_revision_id:
            revision = await self.db.get(
                KnowledgeCategoryRevision,
                jobs_category.active_revision_id,
            )
            if revision:
                known_ids = {
                    str(item["id"])
                    for item in revision.normalized_payload.get("jobs", [])
                    if isinstance(item, dict) and item.get("id")
                }
        validate_job_references(document, known_ids)

    async def _replace_projection(
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
        await self._clear_projection(project_id, key)
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
            targets = _target_jobs(jobs, record.job_ids)
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
        await self.db.execute(delete(BusRoute).where(BusRoute.project_id == project_id))
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
        await self.db.execute(delete(Job).where(Job.company_id.in_([row.id for row in companies])))
        roles: list[str] = []
        locations: list[str] = []
        for item in document.jobs:
            roles.append(item.title)
            if item.location:
                locations.append(item.location)
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
        category_summary = next(
            (item.summary for item in document.jobs if item.summary),
            None,
        )
        project.index_card = {
            "summary": category_summary or project.summary or f"Cơ hội việc làm tại {project.name}",
            "roles": roles,
            "location": ", ".join(dict.fromkeys(locations)),
            "eligibility": [],
            "highlights": [],
        }
        project.summary = project.index_card["summary"]
        project.discovery_revision += 1
        project.is_active = bool(roles)

    async def _clear_projection(
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
                await self.db.execute(delete(Job).where(Job.company_id.in_(company_ids)))
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
            await self.db.execute(delete(BusRoute).where(BusRoute.project_id == project_id))

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


def _render_units(document: CategoryDocument) -> list[dict]:
    definition = get_category_definition(document.category)
    units: list[dict] = []
    for record in getattr(document, definition.list_field):
        payload = record.model_dump(mode="json", exclude_none=True)
        stable_id = str(payload.get("id"))
        content = f"{definition.label_vi}\n" + "\n".join(
            f"{field}: {json.dumps(value, ensure_ascii=False)}"
            for field, value in payload.items()
        )
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
        units.append(unit)
    return units
