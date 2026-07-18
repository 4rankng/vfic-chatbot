"""Database proof for independent Project category activation and Jobs projection."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models.bus import BusRoute, BusStop
from app.models.company import Company, Project
from app.models.job import Job
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
)
from app.models.user import Role, User
from app.services.knowledge.category_contracts import category_checksum, parse_category_yaml
from app.services.knowledge.category_service import KnowledgeCategoryService

pytestmark = pytest.mark.integration


class _Embedder:
    async def batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3072 for _ in texts]


async def test_jobs_category_activation_replaces_only_its_active_revision(
    integration_session,
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
        "category: jobs\n"
        "jobs:\n"
        "  - id: assembler\n"
        "    title: Công nhân lắp ráp\n"
        "    location: Hải Phòng\n"
        "    summary: Chi tiết dài chỉ thuộc về vị trí tuyển dụng.\n"
    )
    jobs_document = parse_category_yaml("jobs", jobs_source)
    jobs_revision = KnowledgeCategoryRevision(
        category_id=jobs_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.yaml",
        source_yaml=jobs_source,
        normalized_payload=jobs_document.model_dump(mode="json"),
        content_sha256=category_checksum(jobs_document),
        created_by=actor.id,
    )
    integration_session.add(jobs_revision)
    await integration_session.commit()

    service = KnowledgeCategoryService(integration_session)
    await service.activate_revision(
        jobs_revision.id,
        _Embedder(),
        start_category_authority=False,
    )

    await integration_session.refresh(jobs_category)
    await integration_session.refresh(project)
    assert jobs_category.active_revision_id == jobs_revision.id
    assert project.is_active is True
    assert project.category_authority_started is False
    expected_summary = "Category Factory đang tuyển Công nhân lắp ráp tại Hải Phòng."
    assert project.summary == expected_summary
    assert project.index_card["summary"] == expected_summary
    assert project.index_card["highlights"] == ["Có xe đưa đón"]
    assert await integration_session.scalar(
        select(func.count(Job.id))
        .join(Company, Company.id == Job.company_id)
        .where(Company.project_id == project.id)
    ) == 1

    benefits_source = (
        "category: benefits\n"
        "benefits:\n"
        "  - id: health-check\n"
        "    job_ids: [assembler]\n"
        "    name: Khám sức khỏe định kỳ\n"
    )
    benefits_document = parse_category_yaml("benefits", benefits_source)
    benefits_revision = KnowledgeCategoryRevision(
        category_id=benefits_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="benefits.yaml",
        source_yaml=benefits_source,
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
    assert project.category_authority_started is True
    assert job is not None
    assert "Khám sức khỏe định kỳ" in (job.benefits or "")

    replacement_source = (
        "category: jobs\n"
        "jobs:\n"
        "  - id: assembler\n"
        "    title: Công nhân lắp ráp điện tử\n"
        "    location: Hải Phòng\n"
    )
    replacement_document = parse_category_yaml("jobs", replacement_source)
    replacement_revision = KnowledgeCategoryRevision(
        category_id=jobs_category.id,
        revision_no=2,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="jobs.yaml",
        source_yaml=replacement_source,
        normalized_payload=replacement_document.model_dump(mode="json"),
        content_sha256=category_checksum(replacement_document),
        created_by=actor.id,
    )
    integration_session.add(replacement_revision)
    await integration_session.commit()

    await service.activate_revision(replacement_revision.id, _Embedder())
    replacement_job = await integration_session.scalar(
        select(Job)
        .join(Company, Company.id == Job.company_id)
        .where(Company.project_id == project.id)
    )
    assert replacement_job is not None
    assert replacement_job.title == "Công nhân lắp ráp điện tử"
    assert "Khám sức khỏe định kỳ" in (replacement_job.benefits or "")

    # At-least-once worker replay is a no-op and cannot duplicate evidence.
    await service.activate_revision(replacement_revision.id, _Embedder())
    assert await integration_session.scalar(
        select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.category_revision_id == replacement_revision.id
        )
    ) == 1

    transportation_source = (
        "category: transportation\n"
        "transportation:\n"
        "  - id: hp-route\n"
        "    job_ids: [assembler]\n"
        "    name: Tuyến Hải Phòng\n"
        "    direction: round_trip\n"
        "    shift: ca ngày\n"
        "    service_days: [thứ 2, thứ 3]\n"
        "    stops:\n"
        "      - order: 1\n"
        "        name: Cầu Rào\n"
        "        time: '06:30'\n"
        "      - order: 2\n"
        "        name: Nhà máy\n"
        "        time: '07:15'\n"
    )
    transportation_document = parse_category_yaml("transportation", transportation_source)
    transportation_revision = KnowledgeCategoryRevision(
        category_id=transportation_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="transportation.yaml",
        source_yaml=transportation_source,
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
    assert len(route_ids) == 2
    assert await integration_session.scalar(
        select(func.count(BusStop.id)).where(BusStop.route_id.in_(route_ids))
    ) == 4

    contacts_source = (
        "category: contacts\n"
        "contacts:\n"
        "  - id: recruiter\n"
        "    name: Bộ phận tuyển dụng\n"
        "    zalo: Zalo OA\n"
    )
    contacts_document = parse_category_yaml("contacts", contacts_source)
    contacts_revision = KnowledgeCategoryRevision(
        category_id=contacts_category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename="contacts.yaml",
        source_yaml=contacts_source,
        normalized_payload=contacts_document.model_dump(mode="json"),
        content_sha256=category_checksum(contacts_document),
        created_by=actor.id,
    )
    integration_session.add(contacts_revision)
    await integration_session.commit()

    await service.activate_revision(contacts_revision.id, _Embedder())
    await integration_session.refresh(contacts_category)
    assert contacts_category.active_revision_id == contacts_revision.id
