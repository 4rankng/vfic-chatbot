"""Saved legacy categories still cut over and roll back without a data rewrite."""

from copy import deepcopy
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.company import Company, Project
from app.models.job import Job
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import Role, User
from app.project_knowledge.domain.category import category_payload_checksum
from app.services.knowledge import category_authority
from app.services.knowledge.category_contracts import CATEGORY_DEFINITIONS
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.category_service import KnowledgeCategoryService

pytestmark = pytest.mark.integration


async def test_old_payloads_cut_over_as_project_knowledge_and_keep_history_on_rollback(
    integration_session, monkeypatch
):
    db = integration_session
    monkeypatch.setattr(KnowledgeCategoryService, "_repair_caches", AsyncMock())
    monkeypatch.setattr(category_authority, "bump_cache_version", AsyncMock())
    actor = User(
        email=f"legacy-refs-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    project = Project(
        slug=f"legacy-refs-{uuid.uuid4().hex}",
        name="Xưởng tuyển dụng",
        category_authority_started=False,
        index_card={"summary": "Nội dung trước chuyển đổi"},
        summary="Nội dung trước chuyển đổi",
    )
    db.add_all([actor, project])
    await db.flush()
    base = KnowledgeBase(
        name=project.name,
        slug=f"kb-{project.slug}",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
        project_id=project.id,
    )
    db.add(base)
    await db.flush()
    project.knowledge_base_id = base.id
    jobs = {
        "schema_version": "1.0",
        "category": "jobs",
        "jobs": [
            {"id": "operator", "title": "Vận hành máy"},
            {"id": "inspector", "title": "Kiểm tra chất lượng"},
        ],
    }
    benefits = {
        "schema_version": "1.0",
        "category": "benefits",
        "benefits": [
            {
                "id": "food",
                "name": "Cơm ca miễn phí",
                "description": "Một bữa trong mỗi ca",
                "job_ids": ["operator"],
                "jobs_ids": ["old-inspector"],
                "vacancies": None,
                "employment_type": "temporary",
            }
        ],
    }
    legacy_source = (
        '---\nschema_version: "1.0"\ncategory: benefits\n---\n'
        '\n## benefits\n\n### record: food\nname: "Cơm ca miễn phí"\n'
        'job_ids:\n- "operator"\njobs_ids: ["old-inspector"]\n'
        'vacancies: null\nemployment_type: temporary\n'
        'description: "Một bữa trong mỗi ca"\n'
    )
    historical_revision = None
    for definition in CATEGORY_DEFINITIONS:
        category = KnowledgeCategory(project_id=project.id, category_key=definition.key.value)
        db.add(category)
        await db.flush()
        active = definition.key.value in {"jobs", "benefits"}
        payload = (
            jobs
            if definition.key.value == "jobs"
            else benefits
            if active
            else {
                "schema_version": "1.0",
                "category": definition.key.value,
                definition.list_field: [],
            }
        )
        source = (
            legacy_source if definition.key.value == "benefits" else build_source_markdown(payload)
        )
        checksum = category_payload_checksum(payload)
        revision = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=1,
            status=KnowledgeCategoryRevisionStatus.ACTIVE
            if active
            else KnowledgeCategoryRevisionStatus.CLEARED,
            source_filename=f"{definition.key.value}.md",
            source_markdown=source,
            normalized_payload=payload,
            content_sha256=checksum,
            quality_result={
                "checksum": checksum,
                "record_count": len(payload[definition.list_field]),
            },
        )
        db.add(revision)
        await db.flush()
        if active:
            category.active_revision_id = revision.id
            db.add(
                KnowledgeDocument(
                    project_id=project.id,
                    category_revision_id=revision.id,
                    file_name=revision.source_filename,
                    source="category_markdown",
                    raw_text=source,
                    status=KnowledgeStatus.PUBLISHED,
                    stage="PUBLISHED",
                )
            )
        if definition.key.value == "benefits":
            historical_revision = revision
    await db.commit()
    historical = (
        historical_revision.source_markdown,
        deepcopy(historical_revision.normalized_payload),
        historical_revision.content_sha256,
        deepcopy(historical_revision.quality_result),
    )
    service = KnowledgeCategoryService(db, enforce_retrieval_selftest=False)

    await service.cutover_category_authority(project_id=project.id, actor=actor)

    projected = list(
        (
            await db.scalars(
                select(Job)
                .join(Company, Company.id == Job.company_id)
                .where(Company.project_id == project.id)
            )
        ).all()
    )
    assert len(projected) == 2
    for job in projected:
        assert "Cơm ca miễn phí" in job.benefits
        assert "job_ids" not in job.benefits
        assert "jobs_ids" not in job.benefits
    await db.refresh(historical_revision)
    assert (
        historical_revision.source_markdown,
        historical_revision.normalized_payload,
        historical_revision.content_sha256,
        historical_revision.quality_result,
    ) == historical
    snapshot = deepcopy(project.category_cutover_snapshot)
    assert snapshot["category_pointers"]["benefits"] == str(historical_revision.id)

    await service.rollback_category_authority(project_id=project.id, actor=actor)

    await db.refresh(project)
    await db.refresh(base)
    await db.refresh(historical_revision)
    assert project.category_authority_started is False
    assert base.mode is KnowledgeBaseMode.DIRECT_CONTEXT
    assert project.index_card == {"summary": "Nội dung trước chuyển đổi"}
    assert historical_revision.status is KnowledgeCategoryRevisionStatus.ACTIVE
    assert (
        historical_revision.source_markdown,
        historical_revision.normalized_payload,
        historical_revision.content_sha256,
        historical_revision.quality_result,
    ) == historical
