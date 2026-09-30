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
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.services.knowledge.derived_jobs import rebuild_project_jobs
from app.services.retrieval.catalog_repository import CatalogRepository

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

    lookup = await CatalogRepository(
        integration_session, page_project_ids=None
    ).list_active_projects()
    rorze = next(row for row in lookup if row.project_id == str(project.id))
    assert (rorze.company, rorze.slug) == ("Rorze", "rorze-direct")
    assert [item.title for item in rorze.scope] == [
        "Nhân viên lắp ráp",
        "Nhân viên vận hành máy CNC",
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
    knowledge_base = KnowledgeBase(
        project_id=project.id,
        name="LG Display Knowledge",
        slug="lg-display-kb",
        mode=KnowledgeBaseMode.RAG,
    )
    integration_session.add(knowledge_base)
    await integration_session.flush()
    project.knowledge_base_id = knowledge_base.id
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

    lookup = await CatalogRepository(
        integration_session, page_project_ids=None
    ).list_active_projects()
    rebuilt = next(row for row in lookup if row.project_id == str(project.id))
    assert {item.title for item in rebuilt.scope} == {
        "Công nhân kiểm tra",
    }


async def _seed_take_home_income(
    session, project_id, *, value_json, feature_id
) -> None:
    """Insert a take_home_income feature value for a project."""
    session.add(
        JobFeatureValue(
            project_id=project_id,
            feature_id=feature_id,
            value_text="Thu nhập ước tính",
            value_json=value_json,
            strength_score=0.9,
            display_priority=1,
            is_highlight=True,
            is_missing=False,
            needs_clarification=False,
        )
    )
    await session.flush()


async def _take_home_income_catalog(session) -> WorkerFeatureCatalog:
    """Fetch or create the seeded take_home_income catalog row."""
    row = await session.scalar(
        select(WorkerFeatureCatalog).where(
            WorkerFeatureCatalog.feature_key == "take_home_income"
        )
    )
    if row is not None:
        return row
    row = WorkerFeatureCatalog(
        feature_key="take_home_income",
        name_vi="Thu nhập thực nhận",
        category="salary",
        default_importance_score=0.95,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def test_rebuild_project_jobs_projects_take_home_income_to_salary(
    integration_session,
):
    """Salary in take_home_income.value_json reaches Job.salary_min/salary_max.

    Regression for the bug where structured-project salaries vanished because the
    old ``_optional_int`` dropped any non-int shape (strings, small-int-with-unit).
    """
    catalog = await _take_home_income_catalog(integration_session)
    project = Project(
        slug="salary-proj",
        name="Salary Project",
        is_active=True,
        summary="Tuyển công nhân.",
        index_card={"company_name": "Salary Project", "key_roles": ["Công nhân"]},
    )
    integration_session.add(project)
    await integration_session.flush()
    company = Company(project_id=project.id, name="Salary Project", aliases=[])
    integration_session.add(company)
    await integration_session.flush()
    document = KnowledgeDocument(
        file_name="salary.md",
        status=KnowledgeStatus.PUBLISHED,
        stage="PUBLISHED",
        project_id=project.id,
        raw_text="Salary Project tuyển công nhân.",
    )
    integration_session.add(document)
    await integration_session.flush()
    await KnowledgeChunkRepo(integration_session).replace_for_doc(
        document,
        [
            (
                {
                    "content": "Salary Project tuyển công nhân.",
                    "source_quote": "Salary Project tuyển công nhân.",
                    "summary": "Salary Project tuyển công nhân.",
                    "questions": ["Tuyển vị trí gì?"],
                    "category": "job",
                    "entities": {"job_title": "Công nhân"},
                    "source_anchor": "§ Công việc",
                    "confidence": "high",
                    "is_inference": False,
                },
                [0.01] * 3072,
            )
        ],
    )
    # Canonical shape: full VND integers.
    await _seed_take_home_income(
        integration_session,
        project.id,
        value_json={"min": 10_000_000, "max": 13_000_000, "currency": "VND"},
        feature_id=catalog.id,
    )

    await rebuild_project_jobs(
        integration_session,
        project_id=project.id,
        source_document_id=document.id,
    )

    job = await integration_session.scalar(
        select(Job).where(Job.company_id == company.id, Job.title == "Công nhân")
    )
    assert job is not None
    assert job.salary_min == 10_000_000
    assert job.salary_max == 13_000_000


async def test_rebuild_project_jobs_coerces_string_and_unit_salary_shapes(
    integration_session,
):
    """LLM-returned strings and seed-style small-int-with-unit both reach VND."""
    catalog = await _take_home_income_catalog(integration_session)
    project = Project(
        slug="string-salary-proj",
        name="String Salary Project",
        is_active=True,
        summary="Tuyển công nhân.",
        index_card={"company_name": "String Salary Project", "key_roles": ["Công nhân"]},
    )
    integration_session.add(project)
    await integration_session.flush()
    company = Company(project_id=project.id, name="String Salary Project", aliases=[])
    integration_session.add(company)
    await integration_session.flush()
    document = KnowledgeDocument(
        file_name="string_salary.md",
        status=KnowledgeStatus.PUBLISHED,
        stage="PUBLISHED",
        project_id=project.id,
        raw_text="String Salary Project tuyển công nhân.",
    )
    integration_session.add(document)
    await integration_session.flush()
    await KnowledgeChunkRepo(integration_session).replace_for_doc(
        document,
        [
            (
                {
                    "content": "String Salary Project tuyển công nhân.",
                    "source_quote": "String Salary Project tuyển công nhân.",
                    "summary": "String Salary Project tuyển công nhân.",
                    "questions": ["Tuyển vị trí gì?"],
                    "category": "job",
                    "entities": {"job_title": "Công nhân"},
                    "source_anchor": "§ Công việc",
                    "confidence": "high",
                    "is_inference": False,
                },
                [0.01] * 3072,
            )
        ],
    )
    # Seed-style shape: small ints with "triệu VNĐ" unit marker.
    await _seed_take_home_income(
        integration_session,
        project.id,
        value_json={"min": 10, "max": 13, "unit": "triệu VNĐ"},
        feature_id=catalog.id,
    )

    await rebuild_project_jobs(
        integration_session,
        project_id=project.id,
        source_document_id=document.id,
    )

    job = await integration_session.scalar(
        select(Job).where(Job.company_id == company.id, Job.title == "Công nhân")
    )
    assert job is not None
    assert job.salary_min == 10_000_000
    assert job.salary_max == 13_000_000
