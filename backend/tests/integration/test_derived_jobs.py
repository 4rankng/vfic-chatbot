from __future__ import annotations

from sqlalchemy import func, select

from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.derived_jobs import rebuild_project_jobs
from app.services.recommendation.repository import RecommendationRepository


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
