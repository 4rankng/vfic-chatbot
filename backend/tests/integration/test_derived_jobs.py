from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.derived_jobs import rebuild_project_jobs
from app.services.recommendation.repository import RecommendationRepository

pytestmark = pytest.mark.integration


async def test_active_single_page_project_is_included_in_vacancy_catalog(
    integration_session,
):
    project = Project(
        slug="rorze-direct",
        name="Rorze",
        aliases=["Công ty Rorze"],
        is_active=True,
        summary="Tuyển nhân viên lắp ráp và vận hành máy CNC.",
        index_card={
            "roles": ["Nhân viên lắp ráp", "Nhân viên vận hành máy CNC"],
            "location": "KCN Nội Bài, Hà Nội",
        },
    )
    integration_session.add(project)
    await integration_session.flush()
    knowledge_base = KnowledgeBase(
        project_id=project.id,
        name="Rorze Knowledge",
        slug="rorze-direct-kb",
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
    integration_session.add(
        KnowledgeBaseDirectFile(
            knowledge_base_id=knowledge_base.id,
            filename="rorze.md",
            raw_text="Rorze tuyển nhân viên lắp ráp và vận hành máy CNC.",
            normalized_text="Rorze tuyển nhân viên lắp ráp và vận hành máy CNC.",
            content_sha256="a" * 64,
            char_count=55,
            line_count=1,
        )
    )
    await integration_session.flush()

    lookup = await RecommendationRepository(integration_session).list_active_jobs(
        role="lắp ráp",
        project_ids=[str(project.id)],
        top_k=10,
    )

    assert lookup.status == "matched"
    assert [(job.company_name, job.project_slug) for job in lookup.jobs] == [
        ("Rorze", "rorze-direct")
    ]


async def test_rebuild_project_jobs_mirrors_current_kb_and_is_idempotent(
    integration_session,
):
    project = Project(
        slug="lg-display",
        name="LG Display",
        is_active=True,
        summary="LG Display tuyển công nhân sản xuất.",
        index_card={
            "company_name": "LG Display",
            "key_roles": ["Công nhân sản xuất"],
            "location": "Hải Phòng",
            "highlights": ["Có xe đưa đón"],
        },
    )
    integration_session.add(project)
    await integration_session.flush()
    company = Company(project_id=project.id, name="LG Display", aliases=["LGD"])
    integration_session.add(company)
    await integration_session.flush()
    old_job = Job(
        company_id=company.id,
        title="Vị trí cũ",
        status=JobStatus.ACTIVE,
        vacancy_count=5,
    )
    current_job = Job(
        company_id=company.id,
        title="Công nhân kiểm tra",
        status=JobStatus.FULL,
        vacancy_count=0,
    )
    document = KnowledgeDocument(
        file_name="lg.md",
        status=KnowledgeStatus.PUBLISHED,
        stage="PUBLISHED",
        project_id=project.id,
        raw_text="LG Display tuyển công nhân kiểm tra.",
    )
    integration_session.add_all([old_job, current_job, document])
    await integration_session.flush()
    unit = {
        "content": "LG Display tuyển công nhân kiểm tra.",
        "source_quote": "LG Display tuyển công nhân kiểm tra.",
        "summary": "LG Display tuyển công nhân kiểm tra.",
        "questions": ["LG Display tuyển vị trí gì?"],
        "category": "job",
        "entities": {"job_title": "Công nhân kiểm tra"},
        "source_anchor": "§ Công việc",
        "confidence": "high",
        "is_inference": False,
    }
    await KnowledgeChunkRepo(integration_session).replace_for_doc(
        document,
        [(unit, [0.01] * 3072)],
    )

    assert (
        await rebuild_project_jobs(
            integration_session,
            project_id=project.id,
            source_document_id=document.id,
        )
        == 1
    )
    assert (
        await rebuild_project_jobs(
            integration_session,
            project_id=project.id,
            source_document_id=document.id,
        )
        == 1
    )

    jobs = list(
        (
            await integration_session.scalars(
                select(Job).where(Job.company_id == company.id).order_by(Job.title)
            )
        ).all()
    )
    assert len(jobs) == 2
    assert {job.title for job in jobs if job.status == JobStatus.ACTIVE} == {
        "Công nhân kiểm tra",
    }
    assert old_job.status == JobStatus.ARCHIVED
    assert current_job.status == JobStatus.ACTIVE
    assert current_job.source_document_id == document.id
    assert all(job.vacancy_count is None for job in jobs if job.status == JobStatus.ACTIVE)
    assert (
        await integration_session.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.ACTIVE)
        )
        == 1
    )

    lookup = await RecommendationRepository(integration_session).list_active_jobs(
        top_k=10,
        project_ids=[str(project.id)],
    )
    assert lookup.status == "matched"
    assert {job.title for job in lookup.jobs} == {
        "Công nhân kiểm tra",
    }
