"""Project facts project conservatively into every derived recruitment role."""

import json
import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock

from app.models.job import Job, JobStatus
from app.models.company import Company, Project
from app.services.knowledge.category_contracts import validate_category_payload
from app.services.knowledge.category_projections import SqlAlchemyCategoryProjectionWriter
from app.schemas.knowledge_categories import CategoryDocument
from app.shared.domain.errors import NotFoundError


class _ProjectJobs:
    def __init__(self):
        self.jobs = [Job(stable_key="assembly"), Job(stable_key="packing")]

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.jobs)


async def _apply(key, records):
    session = _ProjectJobs()
    document = validate_category_payload(key, {"category": key, key: records})
    writer = SqlAlchemyCategoryProjectionWriter(session)
    await writer._apply_projection_records(uuid.uuid4(), document, SimpleNamespace())
    return session.jobs


@pytest.mark.parametrize(
    ("key", "records", "field", "value"),
    [
        ("compensation", [{"id": "pay", "base_salary_vnd": 6_000_000}], "salary_min", 6_000_000),
        ("requirements", [{"id": "eligible", "age_min": 18}], "age_min", 18),
        ("benefits", [{"id": "health", "name": "Khám sức khỏe"}], "benefits", "Khám sức khỏe"),
        ("accommodation", [{"id": "housing", "available": False}], "accommodation_support", False),
        ("meals", [{"id": "lunch", "provided": True}], "meal_support", True),
    ],
)
async def test_project_facts_reach_every_derived_role_without_associations(
    key, records, field, value
):
    jobs = await _apply(key, records)
    assert [getattr(job, field) for job in jobs] == [value, value]


async def test_zero_income_is_not_replaced_by_base_salary():
    jobs = await _apply(
        "compensation",
        [
            {
                "id": "training",
                "base_salary_vnd": 6_000_000,
                "estimated_income_min_vnd": 0,
                "estimated_income_max_vnd": 0,
            }
        ],
    )
    assert [(job.salary_min, job.salary_max) for job in jobs] == [(0, 0), (0, 0)]


@pytest.mark.parametrize(
    "records",
    [
        [{"id": "a", "base_salary_vnd": 6_000_000}, {"id": "b", "base_salary_vnd": 8_000_000}],
        [{"id": "a", "base_salary_vnd": 6_000_000}, {"id": "b", "payment_notes": "Theo hợp đồng"}],
    ],
)
async def test_conflicting_or_incomplete_income_does_not_become_a_role_promise(records):
    jobs = await _apply("compensation", records)
    assert [(job.salary_min, job.salary_max) for job in jobs] == [(None, None), (None, None)]


async def test_agreed_income_is_available_even_with_multiple_records():
    jobs = await _apply(
        "compensation",
        [
            {"id": "a", "base_salary_vnd": 6_000_000},
            {"id": "b", "base_salary_vnd": 6_000_000, "payment_notes": "Theo tháng"},
        ],
    )
    assert [(job.salary_min, job.salary_max) for job in jobs] == [(6_000_000, 6_000_000)] * 2


async def test_conflicting_eligibility_is_unknown_but_all_requirements_remain_available():
    records = [
        {
            "id": "a",
            "age_min": 18,
            "age_max": 35,
            "genders": ["female"],
            "experience": "Có kinh nghiệm",
        },
        {
            "id": "b",
            "age_min": 21,
            "age_max": 45,
            "genders": ["male"],
            "experience": "Được đào tạo",
        },
    ]
    jobs = await _apply("requirements", records)
    for job in jobs:
        assert (job.age_min, job.age_max, job.gender_requirement, job.experience_required) == (
            None,
        ) * 4
        assert [json.loads(line)["id"] for line in job.requirements.splitlines()] == ["a", "b"]


@pytest.mark.parametrize(
    ("key", "records", "field"),
    [
        (
            "accommodation",
            [{"id": "a", "available": True}, {"id": "b", "available": False}],
            "accommodation_support",
        ),
        ("meals", [{"id": "a", "provided": True}, {"id": "b", "provided": False}], "meal_support"),
    ],
)
async def test_conflicting_support_is_unknown_instead_of_last_record_winning(key, records, field):
    jobs = await _apply(key, records)
    assert [getattr(job, field) for job in jobs] == [None, None]


async def test_every_schedule_and_benefit_is_retained_for_the_project():
    schedules = await _apply(
        "work_schedules",
        [
            {"id": "day", "notes": "Ca ngày"},
            {"id": "night", "notes": "Ca đêm"},
        ],
    )
    for job in schedules:
        assert [json.loads(line)["notes"] for line in job.shift.splitlines()] == [
            "Ca ngày",
            "Ca đêm",
        ]
    benefits = await _apply(
        "benefits",
        [
            {"id": "health", "name": "Khám sức khỏe"},
            {"id": "holiday", "name": "Nghỉ phép", "description": "Theo quy định"},
        ],
    )
    assert [job.benefits for job in benefits] == ["Khám sức khỏe\nNghỉ phép\nTheo quy định"] * 2


async def test_jobs_projection_requires_an_existing_project_before_writing_rows():
    session = AsyncMock()
    session.get.return_value = None
    writer = SqlAlchemyCategoryProjectionWriter(session)
    document = validate_category_payload(
        "jobs",
        {
            "category": "jobs",
            "jobs": [{"id": "assembly", "title": "Lắp ráp"}],
        },
    )
    with pytest.raises(NotFoundError, match="Project not found"):
        await writer._replace_jobs(uuid.uuid4(), SimpleNamespace(), document)
    session.scalars.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.parametrize("projection", ["_replace_jobs", "_replace_transportation_routes"])
async def test_projection_rejects_a_document_without_its_typed_records_before_io(projection):
    session = AsyncMock()
    writer = SqlAlchemyCategoryProjectionWriter(session)
    document = CategoryDocument(category="jobs")
    with pytest.raises(ValueError, match="requires its category document"):
        await getattr(writer, projection)(uuid.uuid4(), SimpleNamespace(), document)
    session.get.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("existing_count", [None, 0, 37])
async def test_kb_projection_keeps_existing_job_counts_and_never_invents_new_vacancies(
    existing_count,
):
    project = Project(id=uuid.uuid4(), name="Xưởng", aliases=[], discovery_revision=0)
    company = Company(id=uuid.uuid4(), project_id=project.id, name=project.name)
    revision = SimpleNamespace(id=uuid.uuid4())
    existing = Job(
        company_id=company.id,
        stable_key="assembly",
        title="Lắp ráp cũ",
        status=JobStatus.ACTIVE,
        vacancy_count=existing_count,
        source_category_revision_id=uuid.uuid4(),
    )
    session = AsyncMock()
    session.get.return_value = project
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda: [company]),
        SimpleNamespace(all=lambda: [existing]),
    ]
    session.add = Mock()
    document = validate_category_payload(
        "jobs",
        {
            "category": "jobs",
            "jobs": [
                {"id": "assembly", "title": "Lắp ráp"},
                {"id": "packing", "title": "Đóng gói"},
            ],
        },
    )
    await SqlAlchemyCategoryProjectionWriter(session)._replace_jobs(project.id, revision, document)
    assert existing.title == "Lắp ráp"
    assert existing.vacancy_count == existing_count
    new_job = session.add.call_args.args[0]
    assert isinstance(new_job, Job)
    assert new_job.stable_key == "packing"
    assert new_job.vacancy_count is None
