"""Database proof for independent Project category activation and Jobs projection."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from sqlalchemy import delete, func, select, text, update

from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
from app.models.bus import BusRoute, BusStop
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import (
    KBVersion,
    KBVersionStatus,
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import Role, User
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.job_service import JobService
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    category_checksum,
)
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.base_service import KnowledgeBaseService
from app.services.knowledge.category_service import (
    CategoryActivationError,
    KnowledgeCategoryService,
)
from app.services.project.repository import ProjectRepository
from app.services.retrieval.catalog_repository import CatalogRepository
from app.services.retrieval.repository import RetrievalRepository
from app.shared.domain.errors import ConflictError

pytestmark = pytest.mark.integration


class _Embedder:
    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3072 for _ in texts]


class _CapturingEmbedder(_Embedder):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def batch(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return await super().batch(texts)


class _FailingEmbedder:
    async def batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("secret-contact-+84909999999")


async def test_repository_visibility_uses_active_category_and_pre_cutover_legacy_only(
    integration_session,
) -> None:
    actor = User(
        email=f"visibility-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        name="Visibility Factory",
        slug=f"visibility-{uuid.uuid4().hex}",
        category_authority_started=False,
    )
    integration_session.add_all([actor, project])
    await integration_session.flush()

    base = KnowledgeBase(
        name=project.name,
        slug=f"visibility-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
    )
    integration_session.add(base)
    await integration_session.flush()
    project.knowledge_base_id = base.id

    legacy_version = KBVersion(
        project_id=project.id,
        version_no=1,
        status=KBVersionStatus.ACTIVE,
        created_by=actor.id,
    )
    category = KnowledgeCategory(project_id=project.id, category_key="faq")
    integration_session.add_all([legacy_version, category])
    await integration_session.flush()
    project.active_kb_version_id = legacy_version.id

    active_revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=2,
        status=KnowledgeCategoryRevisionStatus.ACTIVE,
        source_filename="faq.md",
        source_markdown="---\nschema_version: \"1.0\"\ncategory: faq\n---\n\n## faq\n",
        normalized_payload={"category": "faq", "faq": []},
        content_sha256="a" * 64,
        created_by=actor.id,
    )
    inactive_revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.ARCHIVED,
        source_filename="faq.md",
        source_markdown="---\nschema_version: \"1.0\"\ncategory: faq\n---\n\n## faq\n",
        normalized_payload={"category": "faq", "faq": []},
        content_sha256="b" * 64,
        created_by=actor.id,
    )
    integration_session.add_all([active_revision, inactive_revision])
    await integration_session.flush()
    category.active_revision_id = active_revision.id

    active_document = KnowledgeDocument(
        file_name="active-faq.md",
        source="category_markdown",
        status=KnowledgeStatus.PUBLISHED,
        project_id=project.id,
        category_revision_id=active_revision.id,
    )
    inactive_document = KnowledgeDocument(
        file_name="inactive-faq.md",
        source="category_markdown",
        status=KnowledgeStatus.PUBLISHED,
        project_id=project.id,
        category_revision_id=inactive_revision.id,
    )
    legacy_document = KnowledgeDocument(
        file_name="legacy.md",
        source="legacy",
        status=KnowledgeStatus.PUBLISHED,
        project_id=project.id,
    )
    integration_session.add_all([active_document, inactive_document, legacy_document])
    await integration_session.flush()

    vector = "[" + ",".join(["0.1"] * 3072) + "]"
    chunk_specs = [
        (active_document.id, active_revision.id, None, "shared evidence active"),
        (inactive_document.id, inactive_revision.id, None, "shared evidence inactive"),
        (legacy_document.id, None, legacy_version.id, "shared evidence legacy"),
    ]
    for document_id, revision_id, version_id, content in chunk_specs:
        await integration_session.execute(
            text(
                "INSERT INTO knowledge_chunks (document_id, category_revision_id, "
                "kb_version_id, chunk_index, chunk_type, section_path, content, "
                "content_plain, token_count, embedding, metadata, project_id, "
                "search_text) VALUES (CAST(:document_id AS uuid), "
                "CAST(:revision_id AS uuid), CAST(:version_id AS uuid), 0, "
                "'category_record', CAST(:section_path AS text[]), :content, "
                ":content, 3, CAST(:vector AS vector), CAST('{}' AS jsonb), "
                "CAST(:project_id AS uuid), public.normalize_search_text(:content))"
            ),
            {
                "document_id": str(document_id),
                "revision_id": str(revision_id) if revision_id else None,
                "version_id": str(version_id) if version_id else None,
                "section_path": [],
                "content": content,
                "vector": vector,
                "project_id": str(project.id),
            },
        )
    await integration_session.commit()

    repository = RetrievalRepository(integration_session)

    async def visible_contents() -> set[str]:
        rows = await repository._documents._match_document_vector_rows(
            emb=vector,
            top_k=10,
            filter_json="{}",
            project_clause="AND d.project_id = ANY(CAST(:pids AS uuid[]))",
            project_ids=[str(project.id)],
        )
        return {row.content for row in rows}

    assert await visible_contents() == {"shared evidence legacy"}

    project.category_authority_started = True
    await integration_session.commit()

    assert await visible_contents() == {"shared evidence active"}


async def test_jobs_category_activation_replaces_only_its_active_revision(
    integration_session,
    monkeypatch,
) -> None:
    actor = User(
        email=f"category-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    legacy_summary = "Chi tiết dài từ tài liệu cũ không phải là tóm tắt dự án."
    project = Project(
        name="Category Factory",
        slug=f"category-{uuid.uuid4().hex}",
        summary=legacy_summary,
        # Seeded inactive: the admin owns the switch, so even a projection that
        # runs must leave this value alone.
        is_active=False,
        index_card={"summary": legacy_summary, "highlights": ["Có xe đưa đón"]},
    )
    integration_session.add_all([actor, project])
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Category Factory Knowledge",
        slug=f"category-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    jobs_category = KnowledgeCategory(project_id=project.id, category_key="jobs")
    benefits_category = KnowledgeCategory(project_id=project.id, category_key="benefits")
    transportation_category = KnowledgeCategory(
        project_id=project.id,
        category_key="transportation",
    )
    contacts_category = KnowledgeCategory(project_id=project.id, category_key="contacts")
    integration_session.add_all(
        [jobs_category, benefits_category, transportation_category, contacts_category]
    )
    await integration_session.flush()

    jobs_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n"
        "### record: assembler\n"
        'title: "Công nhân lắp ráp"\n'
        'location: "Hải Phòng"\n'
        'summary: "Chi tiết dài chỉ thuộc về vị trí tuyển dụng."\n'
    )
    jobs_document = parse_category_markdown("jobs", jobs_source)
    jobs_revision = KnowledgeCategoryRevision(
        category_id=jobs_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.md",
        source_markdown=jobs_source,
        normalized_payload=jobs_document.model_dump(mode="json"),
        content_sha256=category_checksum(jobs_document),
        created_by=actor.id,
    )
    integration_session.add(jobs_revision)
    await integration_session.commit()

    service = KnowledgeCategoryService(
        integration_session, enforce_retrieval_selftest=False
    )
    await service.activate_revision(
        jobs_revision.id,
        _Embedder(),
        start_category_authority=False,
    )

    await integration_session.refresh(jobs_category)
    await integration_session.refresh(project)
    assert jobs_category.active_revision_id == jobs_revision.id
    assert project.is_active is False
    assert project.category_authority_started is False
    assert project.summary == legacy_summary
    assert project.index_card["summary"] == legacy_summary
    assert project.index_card["highlights"] == ["Có xe đưa đón"]
    assert await integration_session.scalar(
        select(func.count(Job.id))
        .join(Company, Company.id == Job.company_id)
        .where(Company.project_id == project.id)
    ) == 0

    benefits_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: benefits\n"
        "---\n"
        "\n"
        "## benefits\n"
        "\n"
        "### record: health-check\n"
        'name: "Khám sức khỏe định kỳ"\n'
    )
    benefits_document = parse_category_markdown("benefits", benefits_source)
    benefits_revision = KnowledgeCategoryRevision(
        category_id=benefits_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="benefits.md",
        source_markdown=benefits_source,
        normalized_payload=benefits_document.model_dump(mode="json"),
        content_sha256=category_checksum(benefits_document),
        created_by=actor.id,
    )
    integration_session.add(benefits_revision)
    await integration_session.commit()

    await service.activate_revision(benefits_revision.id, _Embedder())

    await integration_session.refresh(jobs_category)
    await integration_session.refresh(benefits_category)
    await integration_session.refresh(project)
    job = await integration_session.scalar(
        select(Job)
        .join(Company, Company.id == Job.company_id)
        .where(Company.project_id == project.id)
    )
    assert jobs_category.active_revision_id == jobs_revision.id
    assert benefits_category.active_revision_id == benefits_revision.id
    assert project.category_authority_started is False
    assert job is None

    replacement_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n"
        "### record: assembler\n"
        'title: "Công nhân lắp ráp điện tử"\n'
        'location: "Hải Phòng"\n'
    )
    replacement_document = parse_category_markdown("jobs", replacement_source)
    replacement_revision = KnowledgeCategoryRevision(
        category_id=jobs_category.id,
        revision_no=2,
        status=KnowledgeCategoryRevisionStatus.PROCESSING,
        source_filename="jobs.md",
        source_markdown=replacement_source,
        normalized_payload=replacement_document.model_dump(mode="json"),
        content_sha256=category_checksum(replacement_document),
        created_by=actor.id,
        processing_token=uuid.uuid4(),
        processing_started_at=datetime.now(UTC) - timedelta(hours=2),
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        attempt_count=1,
    )
    integration_session.add(replacement_revision)
    await integration_session.commit()

    enqueued: list[uuid.UUID] = []
    monkeypatch.setattr(
        "app.workers.category_worker.enqueue_category_revision",
        lambda revision_id: enqueued.append(revision_id)
        or f"category-revision-{revision_id}",
    )
    reused, receipt_id = await service.stage_replacement(
        project_id=project.id,
        category_key=KnowledgeCategoryKey.JOBS,
        filename="jobs.md",
        source_markdown=replacement_source,
        actor=actor,
    )
    assert reused.id == replacement_revision.id
    assert receipt_id == f"category-revision-{replacement_revision.id}"
    assert enqueued == [replacement_revision.id]

    await service.activate_revision(replacement_revision.id, _Embedder())
    replacement_job = await integration_session.scalar(
        select(Job)
        .join(Company, Company.id == Job.company_id)
        .where(Company.project_id == project.id)
    )
    assert replacement_job is None
    await integration_session.refresh(replacement_revision)
    assert replacement_revision.attempt_count == 2

    # At-least-once worker replay is a no-op and cannot duplicate evidence.
    await service.activate_revision(replacement_revision.id, _Embedder())
    assert await integration_session.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.category_revision_id == replacement_revision.id
        )
    ) == 1

    transportation_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: transportation\n"
        "---\n"
        "\n"
        "## transportation\n"
        "\n"
        "### record: hp-route\n"
        'name: "Tuyến Hải Phòng"\n'
        'direction: "round_trip"\n'
        'shift: "ca ngày"\n'
        "service_days:\n"
        '- "thứ 2"\n'
        '- "thứ 3"\n'
        "stops:\n"
        "| order | name | time | address |\n"
        "| --- | --- | --- | --- |\n"
        '| 1 | "Cầu Rào" | "06:30" | null |\n'
        '| 2 | "Nhà máy" | "07:15" | null |\n'
    )
    transportation_document = parse_category_markdown("transportation", transportation_source)
    transportation_revision = KnowledgeCategoryRevision(
        category_id=transportation_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="transportation.md",
        source_markdown=transportation_source,
        normalized_payload=transportation_document.model_dump(mode="json"),
        content_sha256=category_checksum(transportation_document),
        created_by=actor.id,
    )
    integration_session.add(transportation_revision)
    await integration_session.commit()

    await service.activate_revision(transportation_revision.id, _Embedder())
    route_ids = list(
        await integration_session.scalars(
            select(BusRoute.id).where(BusRoute.project_id == project.id)
        )
    )
    assert route_ids == []

    contacts_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: contacts\n"
        "---\n"
        "\n"
        "## contacts\n"
        "\n"
        "### record: recruiter\n"
        'name: "Bộ phận tuyển dụng"\n'
        'role: "Tư vấn tuyển dụng"\n'
        'phone: "+84901234567"\n'
        'zalo: "zalo-recruiter"\n'
        'email: "recruiter@example.test"\n'
        'address: "12 Đường Nhà Máy, Hải Phòng"\n'
        'working_hours: "08:00-17:00"\n'
        'notes: "Liên hệ trực tiếp"\n'
    )
    contacts_document = parse_category_markdown("contacts", contacts_source)
    contacts_revision = KnowledgeCategoryRevision(
        category_id=contacts_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="contacts.md",
        source_markdown=contacts_source,
        normalized_payload=contacts_document.model_dump(mode="json"),
        content_sha256=category_checksum(contacts_document),
        created_by=actor.id,
    )
    integration_session.add(contacts_revision)
    await integration_session.commit()

    capturing_embedder = _CapturingEmbedder()
    await service.activate_revision(contacts_revision.id, capturing_embedder)
    await integration_session.refresh(contacts_category)
    await integration_session.refresh(contacts_revision)
    await integration_session.refresh(project)
    assert contacts_category.active_revision_id == contacts_revision.id
    assert project.category_authority_started is False
    assert capturing_embedder.texts == [
        'Liên hệ\nid: "recruiter"\nname: "Bộ phận tuyển dụng"\n'
        'role: "Tư vấn tuyển dụng"\nphone: "+84901234567"\n'
        'zalo: "zalo-recruiter"\nemail: "recruiter@example.test"\n'
        'address: "12 Đường Nhà Máy, Hải Phòng"\nworking_hours: "08:00-17:00"\n'
        'notes: "Liên hệ trực tiếp"'
    ]
    persisted_contact = await integration_session.scalar(
        select(KnowledgeChunk.content).where(
            KnowledgeChunk.category_revision_id == contacts_revision.id
        )
    )
    assert persisted_contact == capturing_embedder.texts[0]
    assert contacts_revision.quality_result["record_count"] == 1
    assert contacts_revision.quality_result["embedding_count"] == 1
    assert contacts_revision.processing_token is None


async def test_explicit_cutover_requires_all_categories_and_rolls_back(
    integration_session,
) -> None:
    actor = User(
        email=f"cutover-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        name="Cutover Factory",
        slug=f"cutover-{uuid.uuid4().hex}",
        category_authority_started=False,
        summary="Legacy factory summary",
        index_card={"summary": "Legacy factory summary", "highlights": ["Legacy"]},
    )
    integration_session.add_all([actor, project])
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Cutover Knowledge",
        slug=f"cutover-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    company = Company(project_id=project.id, name=project.name)
    integration_session.add(company)
    await integration_session.flush()
    legacy_job = Job(
        company_id=company.id,
        title="Legacy operator",
        status="ACTIVE",
        vacancy_count=3,
    )
    legacy_route = BusRoute(
        project_id=project.id,
        company_id=company.id,
        route_name="Legacy route",
        route_variant="legacy",
        shift="day",
        direction="outbound",
        source_page="legacy.md",
        route_group_key="legacy",
    )
    integration_session.add_all([legacy_job, legacy_route])
    await integration_session.flush()
    integration_session.add(
        BusStop(route_id=legacy_route.id, stop_order=1, stop_name="Legacy stop")
    )

    jobs_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n"
        "### record: cutover-job\n"
        'title: "Category operator"\n'
        'location: "Hải Phòng"\n'
    )
    transportation_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: transportation\n"
        "---\n"
        "\n"
        "## transportation\n"
        "\n"
        "### record: category-route\n"
        'name: "Category route"\n'
        'direction: "to_factory"\n'
        "stops:\n"
        "| order | name | time | address |\n"
        "| --- | --- | --- | --- |\n"
        '| 1 | "Category stop" | null | null |\n'
    )

    categories: list[KnowledgeCategory] = []
    for definition in CATEGORY_DEFINITIONS:
        category = KnowledgeCategory(
            project_id=project.id,
            category_key=definition.key.value,
        )
        integration_session.add(category)
        await integration_session.flush()
        source = (
            jobs_source
            if definition.key is KnowledgeCategoryKey.JOBS
            else transportation_source
            if definition.key is KnowledgeCategoryKey.TRANSPORTATION
            else (
                "---\n"
                'schema_version: "1.0"\n'
                f"category: {definition.key.value}\n"
                "---\n"
                "\n"
                f"## {definition.list_field}\n"
            )
        )
        is_active = definition.key in {
            KnowledgeCategoryKey.JOBS,
            KnowledgeCategoryKey.TRANSPORTATION,
        }
        parsed = parse_category_markdown(definition.key, source, allow_empty=not is_active)
        revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=1,
            status=(
                KnowledgeCategoryRevisionStatus.ACTIVE
                if is_active
                else KnowledgeCategoryRevisionStatus.CLEARED
            ),
            source_filename=definition.template_filename,
            source_markdown=source,
            normalized_payload=parsed.model_dump(mode="json"),
            content_sha256=category_checksum(parsed),
            created_by=actor.id,
            activated_at=datetime.now(UTC) if is_active else None,
        )
        integration_session.add(revision)
        await integration_session.flush()
        if is_active:
            category.active_revision_id = revision.id
        categories.append(category)
    await integration_session.commit()

    service = KnowledgeCategoryService(
        integration_session, enforce_retrieval_selftest=False
    )
    cutover = await service.cutover_category_authority(project_id=project.id, actor=actor)

    assert cutover.category_authority_started is True
    assert cutover.category_cutover_snapshot is not None
    assert len(cutover.category_cutover_snapshot["category_pointers"]) == 12
    original_snapshot = dict(cutover.category_cutover_snapshot)
    await integration_session.refresh(project)
    assert project.summary == "Cutover Factory đang tuyển Category operator tại Hải Phòng."
    jobs = list(
        await integration_session.scalars(
            select(Job)
            .join(Company, Company.id == Job.company_id)
            .where(Company.project_id == project.id)
            .order_by(Job.title)
        )
    )
    assert [job.title for job in jobs] == ["Category operator", "Legacy operator"]
    assert sum(job.source_category_revision_id is not None for job in jobs) == 1
    listed_jobs, listed_total = await JobService(integration_session).list(per_page=10)
    assert listed_total == 1
    assert [job.title for job in listed_jobs] == ["Category operator"]
    assert await JobService(integration_session).get(legacy_job.id) is None
    catalog_after_cutover = await CatalogRepository(
        integration_session, page_project_ids=None
    ).list_active_projects()
    cutover_scope = next(
        row for row in catalog_after_cutover if row.project_id == str(project.id)
    )
    assert [item.title for item in cutover_scope.scope] == ["Category operator"]
    routes = list(
        await integration_session.scalars(
            select(BusRoute).where(BusRoute.project_id == project.id).order_by(BusRoute.route_name)
        )
    )
    assert [route.route_name for route in routes] == ["Category route", "Legacy route"]
    visible_routes = await ProjectRepository(integration_session).list_bus_routes(
        project.id,
        limit=10,
        offset=0,
    )
    assert [route["route_name"] for route in visible_routes] == ["Category route"]

    repeated = await service.cutover_category_authority(project_id=project.id, actor=actor)
    assert repeated.category_cutover_snapshot == original_snapshot

    jobs_category = next(
        category for category in categories if category.category_key == "jobs"
    )
    cutover_jobs_revision_id = jobs_category.active_revision_id
    updated_source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n"
        "### record: cutover-job\n"
        'title: "Updated category operator"\n'
        'location: "Hải Phòng"\n'
    )
    updated_document = parse_category_markdown(KnowledgeCategoryKey.JOBS, updated_source)
    updated_revision = KnowledgeCategoryRevision(
        category_id=jobs_category.id,
        revision_no=2,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.md",
        source_markdown=updated_source,
        normalized_payload=updated_document.model_dump(mode="json"),
        content_sha256=category_checksum(updated_document),
        created_by=actor.id,
    )
    integration_session.add(updated_revision)
    await integration_session.commit()
    await service.activate_revision(updated_revision.id, _Embedder())
    await integration_session.refresh(project)
    assert "Updated category operator" in (project.summary or "")

    rolled_back = await service.rollback_category_authority(project_id=project.id, actor=actor)

    assert rolled_back.category_authority_started is False
    assert rolled_back.category_cutover_snapshot is None
    assert rolled_back.category_cutover_at is None
    assert rolled_back.summary == "Legacy factory summary"
    assert rolled_back.index_card == {
        "summary": "Legacy factory summary",
        "highlights": ["Legacy"],
    }
    await integration_session.refresh(jobs_category)
    await integration_session.refresh(updated_revision)
    assert jobs_category.active_revision_id == cutover_jobs_revision_id
    assert updated_revision.status is KnowledgeCategoryRevisionStatus.ARCHIVED
    remaining_jobs = list(
        await integration_session.scalars(
            select(Job)
            .join(Company, Company.id == Job.company_id)
            .where(Company.project_id == project.id)
        )
    )
    assert [job.title for job in remaining_jobs] == ["Legacy operator"]
    listed_legacy_jobs, listed_legacy_total = await JobService(integration_session).list(
        per_page=10
    )
    assert listed_legacy_total == 1
    assert [job.title for job in listed_legacy_jobs] == ["Legacy operator"]
    catalog_after_rollback = await CatalogRepository(
        integration_session, page_project_ids=None
    ).list_active_projects()
    rollback_scope = next(
        row for row in catalog_after_rollback if row.project_id == str(project.id)
    )
    assert [item.title for item in rollback_scope.scope] == ["Legacy operator"]
    remaining_routes = list(
        await integration_session.scalars(
            select(BusRoute).where(BusRoute.project_id == project.id)
        )
    )
    assert [route.route_name for route in remaining_routes] == ["Legacy route"]
    visible_legacy_routes = await ProjectRepository(integration_session).list_bus_routes(
        project.id,
        limit=10,
        offset=0,
    )
    assert [route["route_name"] for route in visible_legacy_routes] == ["Legacy route"]



async def test_activation_failure_is_sanitized_and_persisted() -> None:
    from app.core import db as db_module

    async with db_module.async_session() as session:
        actor = User(
            email=f"category-failure-{uuid.uuid4().hex}@example.test",
            password_hash="not-used",
            role=Role.admin,
        )
        project = Project(
            name="Failure Isolation Factory",
            slug=f"failure-isolation-{uuid.uuid4().hex}",
        )
        session.add_all([actor, project])
        await session.flush()
        knowledge_base = KnowledgeBase(
            name="Failure Isolation Knowledge",
            slug=f"failure-isolation-kb-{uuid.uuid4().hex}",
            mode=KnowledgeBaseMode.RAG,
            project_id=project.id,
            created_by=actor.id,
        )
        session.add(knowledge_base)
        await session.flush()
        project.knowledge_base_id = knowledge_base.id
        category = KnowledgeCategory(project_id=project.id, category_key="contacts")
        session.add(category)
        await session.flush()
        service = KnowledgeCategoryService(session)
        invalid_source = (
            "---\n"
            'schema_version: "1.0"\n'
            "category: contacts\n"
            "---\n"
            "\n"
            "## contacts\n"
            "\n"
            "### record: recruiter\n"
            'name: "Tuyển dụng"\n'
            "phone: [SECRET-PHONE-123]\n"
        )
        with pytest.raises(ConflictError) as validation_error:
            await service.stage_replacement(
                project_id=project.id,
                category_key=KnowledgeCategoryKey.CONTACTS,
                filename="contacts.md",
                source_markdown=invalid_source,
                actor=actor,
            )
        assert "SECRET-PHONE-123" not in str(validation_error.value)
        assert str(validation_error.value) == "Category content failed validation"
        source = (
            "---\n"
            'schema_version: "1.0"\n'
            "category: contacts\n"
            "---\n"
            "\n"
            "## contacts\n"
            "\n"
            "### record: recruiter\n"
            'name: "Tuyển dụng"\n'
        )
        document = parse_category_markdown("contacts", source)
        failed_revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=1,
            status=KnowledgeCategoryRevisionStatus.STAGED,
            source_filename="contacts.md",
            source_markdown=source,
            normalized_payload=document.model_dump(mode="json"),
            content_sha256=category_checksum(document),
            created_by=actor.id,
        )
        session.add(failed_revision)
        await session.commit()
        revision_id = failed_revision.id
        project_id = project.id
        actor_id = actor.id

        try:
            with pytest.raises(
                CategoryActivationError,
                match="category_activation_failed",
            ) as caught:
                await service.activate_revision(revision_id, _FailingEmbedder())

            persisted = await session.get(KnowledgeCategoryRevision, revision_id)
            assert persisted is not None
            assert "secret-contact" not in str(caught.value)
            assert persisted.failure_code == "category_activation_failed"
            assert persisted.error_message == "Category activation failed"
            assert persisted.processing_token is None
            persisted.attempt_count = 3
            await session.commit()
            with pytest.raises(ConflictError, match="retry limit reached"):
                await service.stage_replacement(
                    project_id=project_id,
                    category_key=KnowledgeCategoryKey.CONTACTS,
                    filename="contacts.md",
                    source_markdown=source,
                    actor=actor,
                )
            await session.refresh(persisted)
            assert persisted.failure_code == "category_retry_exhausted"
        finally:
            await session.rollback()
            await session.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(knowledge_base_id=None)
            )
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.execute(delete(User).where(User.id == actor_id))
            await session.commit()


async def test_maximum_category_batch_completes_within_worker_budget(
    integration_session,
) -> None:
    actor = User(
        email=f"category-performance-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        name="Maximum Batch Factory",
        slug=f"maximum-batch-{uuid.uuid4().hex}",
    )
    integration_session.add_all([actor, project])
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Maximum Batch Knowledge",
        slug=f"maximum-batch-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    category = KnowledgeCategory(project_id=project.id, category_key="jobs")
    integration_session.add(category)
    await integration_session.flush()
    source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: jobs\n"
        "---\n"
        "\n"
        "## jobs\n"
        "\n"
        + "".join(
            f"### record: job-{index}\n"
            f'title: "Công nhân {index}"\n'
            'location: "Hải Phòng"\n'
            "\n"
            for index in range(1000)
        )
    )
    document = parse_category_markdown(KnowledgeCategoryKey.JOBS, source)
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.md",
        source_markdown=source,
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
        created_by=actor.id,
    )
    integration_session.add(revision)
    await integration_session.commit()

    started_at = monotonic()
    await KnowledgeCategoryService(
        integration_session, enforce_retrieval_selftest=False
    ).activate_revision(
        revision.id,
        _Embedder(),
    )
    elapsed_seconds = monotonic() - started_at
    await integration_session.refresh(revision)

    assert revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert revision.quality_result["record_count"] == 1000
    assert revision.quality_result["inserted_chunk_count"] == 1000
    assert elapsed_seconds < 60
    assert elapsed_seconds < INGEST_JOB_TIMEOUT_SECONDS


class _OrthogonalEmbedder:
    """Distinct one-hot vector per distinct text: nothing retrieves anything."""

    async def batch(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for item in texts:
            index = int(hashlib.sha256(item.encode("utf-8")).hexdigest(), 16) % 8
            vectors.append([1.0 if position == index else 0.0 for position in range(8)])
        return vectors


class _SameVectorEmbedder:
    """One shared vector for every text: every query retrieves everything."""

    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] * 3072 for _ in texts]


async def _stage_faq_revision(
    integration_session,
) -> tuple[uuid.UUID, str, uuid.UUID, uuid.UUID]:
    actor = User(
        email=f"category-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(name="Gate Factory", slug=f"gate-{uuid.uuid4().hex}")
    integration_session.add_all([actor, project])
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        name="Gate Factory Knowledge",
        slug=f"gate-kb-{uuid.uuid4().hex}",
        mode=KnowledgeBaseMode.RAG,
        project_id=project.id,
        created_by=actor.id,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    category = KnowledgeCategory(project_id=project.id, category_key="faq")
    integration_session.add(category)
    await integration_session.flush()

    question = "Ca làm việc mấy giờ?"
    source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: faq\n"
        "---\n"
        "\n"
        "## faq\n"
        "\n"
        "### record: shift-hours\n"
        f'question: "{question}"\n'
        'answer: "Ca ngày 08:00-20:00, ca đêm 20:00-08:00."\n'
    )
    document = parse_category_markdown("faq", source)
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="faq.md",
        source_markdown=source,
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
        created_by=actor.id,
    )
    integration_session.add(revision)
    await integration_session.commit()
    return revision.id, question, project.id, actor.id


async def test_activation_retrieval_selftest_blocks_unreachable_record() -> None:
    # The gate's failure path rolls back its own session; run the service on an
    # independent session (mirrors production request isolation) so the staged
    # rows survive the rollback and the persisted failure can be asserted.
    from app.core import db as db_module

    async with db_module.async_session() as session:
        revision_id, question, project_id, actor_id = await _stage_faq_revision(session)
        try:
            with pytest.raises(CategoryActivationError):
                await KnowledgeCategoryService(session).activate_revision(
                    revision_id,
                    _OrthogonalEmbedder(),
                )
            revision = await session.get(KnowledgeCategoryRevision, revision_id)
            assert revision is not None
            await session.refresh(revision)
            assert revision.status is KnowledgeCategoryRevisionStatus.FAILED
            assert revision.failure_code == "category_retrieval_selftest_failed"
            assert revision.error_message is not None
            assert question in revision.error_message
        finally:
            await session.rollback()
            if project_id is not None:
                await session.execute(
                    delete(Project).where(Project.id == project_id)
                )
            if actor_id is not None:
                await session.execute(delete(User).where(User.id == actor_id))
            await session.commit()


async def test_activation_retrieval_selftest_passes_consistent_content(
    integration_session,
) -> None:
    revision_id, _question, _project_id, _actor_id = await _stage_faq_revision(
        integration_session
    )

    await KnowledgeCategoryService(integration_session).activate_revision(
        revision_id,
        _SameVectorEmbedder(),
    )

    revision = await integration_session.get(KnowledgeCategoryRevision, revision_id)
    assert revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert revision.failure_code is None


@pytest.mark.parametrize("legacy_fields", [False, True])
async def test_project_category_can_activate_before_jobs_and_later_projects_to_every_role(
    integration_session,
    legacy_fields,
) -> None:
    db = integration_session
    actor = User(
        email=f"project-scope-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        name="Project facts",
        slug=f"project-scope-{uuid.uuid4().hex}",
        category_authority_started=True,
        is_active=False,
    )
    db.add_all([actor, project])
    await db.flush()
    base = KnowledgeBase(
        name=project.name,
        slug=project.slug,
        project_id=project.id,
        mode=KnowledgeBaseMode.RAG,
        created_by=actor.id,
    )
    db.add(base)
    await db.flush()
    project.knowledge_base_id = base.id
    await db.commit()
    service = KnowledgeCategoryService(db, enforce_retrieval_selftest=False)
    from app.services.knowledge.category_markdown import build_source_markdown

    async def activate(key, records):
        source = build_source_markdown({"schema_version": "1.0", "category": key, key: records})
        if key == "compensation" and legacy_fields:
            source = source.replace(
                "### record: pay\n",
                "### record: pay\njob_ids:\n- obsolete\njobs_ids: [other-obsolete]\n",
            )
        revision, _receipt = await service.stage_replacement(
            project_id=project.id,
            category_key=KnowledgeCategoryKey(key),
            filename=f"{key}.md",
            actor=actor,
            schedule=False,
            source_markdown=source,
        )
        await service.activate_revision(revision.id, _Embedder())
        return revision

    compensation = await activate("compensation", [{"id": "pay", "base_salary_vnd": 6_000_000}])
    await db.refresh(compensation)
    assert compensation.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert compensation.quality_result["schema_check"] == "passed"
    assert "reference_check" not in compensation.quality_result
    assert "job_ids" not in compensation.source_markdown
    assert "jobs_ids" not in compensation.source_markdown
    assert "job_ids" not in str(compensation.normalized_payload)
    source_receipt = await service.get_active_source(project.id, KnowledgeCategoryKey.COMPENSATION)
    assert source_receipt.content == compensation.source_markdown
    assert source_receipt.checksum == compensation.content_sha256
    assert (
        await db.scalar(
            select(func.count(Job.id)).join(Company).where(Company.project_id == project.id)
        )
        == 0
    )

    await activate(
        "jobs", [{"id": "assembly", "title": "Lắp ráp"}, {"id": "packing", "title": "Đóng gói"}]
    )
    jobs = list(
        (await db.scalars(select(Job).join(Company).where(Company.project_id == project.id))).all()
    )
    assert len(jobs) == 2
    assert [(job.salary_min, job.salary_max) for job in jobs] == [(6_000_000, 6_000_000)] * 2
    assert all(job.vacancy_count is None for job in jobs)
    kb_service = KnowledgeBaseService(db)
    assert (await kb_service.list_projects(base.id))[0].active_job_count == 2
    assembly = next(job for job in jobs if job.stable_key == "assembly")
    assembly.vacancy_count = 0
    await db.commit()
    assert (await kb_service.list_projects(base.id))[0].active_job_count == 1
    assembly.vacancy_count = 37
    await db.commit()
    assert (await kb_service.list_projects(base.id))[0].active_job_count == 2
    await activate("jobs", [{"id": "assembly", "title": "Lắp ráp"}])
    # The old packing role remains for history, outside the current KB scope.
    assert (await kb_service.list_projects(base.id))[0].active_job_count == 1
    assert assembly.vacancy_count == 37
    assembly.status = JobStatus.FULL
    await db.commit()
    assert (await kb_service.list_projects(base.id))[0].active_job_count == 0
