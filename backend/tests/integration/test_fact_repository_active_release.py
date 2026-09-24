"""Prove the active-release readers bind to the project's *active* KB version.

These replace the ``inspect.getsource`` pins that used to live in
``tests/test_fact_repository.py``: those asserted the join as source text, so a
``==`` → ``!=`` inversion or a dropped ``IS NULL`` legacy fallback would have
kept passing while the reader returned the wrong rows (or none at all).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.ingestion_template import (
    IngestionTemplate,
    IngestionTemplateVersion,
    KBIngestionRun,
    StructuredFact,
    TemplateVersionStatus,
)
from app.models.job import Job
from app.models.knowledge import KBVersion
from app.models.provenance import JobLocation, JobRequirement, PublishedStatus
from app.project_knowledge.domain.statuses import KBVersionStatus
from app.services.ingestion.fact_repository import query_active_structured_facts
from app.services.knowledge.tools.domain_tools import get_job_locations, get_job_requirements

pytestmark = pytest.mark.integration

RECORD_TYPE = "job_posting"
ARTIFACT = {"record_types": [{"key": RECORD_TYPE, "fields": [{"key": "city"}]}]}
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Release:
    """A project with an active release (v2) and a superseded one (v3)."""

    def __init__(
        self,
        project: Project,
        active: KBVersion,
        other: KBVersion,
        template_version_id: uuid.UUID,
    ) -> None:
        self.project = project
        self.active = active
        self.other = other
        self.template_version_id = template_version_id


async def _seed_release(db: AsyncSession) -> _Release:
    project = Project(name="Fact factory", slug=f"facts-{uuid.uuid4().hex[:10]}")
    template = IngestionTemplate(
        template_key=f"facts-{uuid.uuid4().hex[:10]}", name="Facts", vertical="manufacturing"
    )
    db.add_all([project, template])
    await db.flush()
    template_version = IngestionTemplateVersion(
        template_id=template.id,
        version_no=1,
        status=TemplateVersionStatus.PUBLISHED,
        definition={},
    )
    db.add(template_version)
    await db.flush()

    active = KBVersion(
        project_id=project.id,
        template_version_id=template_version.id,
        version_no=1,
        status=KBVersionStatus.ACTIVE,
    )
    other = KBVersion(
        project_id=project.id,
        template_version_id=template_version.id,
        version_no=2,
        status=KBVersionStatus.DRAFT,
    )
    db.add_all([active, other])
    await db.flush()
    project.active_kb_version_id = active.id

    db.add_all(
        [
            KBIngestionRun(
                kb_version_id=version.id,
                template_version_id=template_version.id,
                manifest_sha256="a" * 64,
            )
            for version in (active, other)
        ]
    )
    await db.flush()
    return _Release(project, active, other, template_version.id)


async def _fact(
    db: AsyncSession,
    *,
    release: _Release,
    project_id: uuid.UUID,
    kb_version_id: uuid.UUID,
    city: str,
) -> StructuredFact:
    run_id = await db.scalar(
        select(KBIngestionRun.id).where(KBIngestionRun.kb_version_id == kb_version_id)
    )
    fact = StructuredFact(
        project_id=project_id,
        kb_version_id=kb_version_id,
        template_version_id=release.template_version_id,
        run_id=run_id,
        record_type_key=RECORD_TYPE,
        natural_key={"city": city},
        natural_key_hash=uuid.uuid4().hex + uuid.uuid4().hex[:32],
        payload={"city": city},
        scope_type="global",
    )
    db.add(fact)
    await db.flush()
    return fact


async def _query(db: AsyncSession, release: _Release):
    return await query_active_structured_facts(
        db,
        project_id=release.project.id,
        template_version_id=release.template_version_id,
        artifact=ARTIFACT,
        record_type_key=RECORD_TYPE,
        filters=[],
        limit=10,
    )


async def test_query_active_structured_facts_returns_only_the_active_release(
    integration_session: AsyncSession,
) -> None:
    release = await _seed_release(integration_session)
    active_fact = await _fact(
        integration_session,
        release=release,
        project_id=release.project.id,
        kb_version_id=release.active.id,
        city="Hải Phòng",
    )
    await _fact(
        integration_session,
        release=release,
        project_id=release.project.id,
        kb_version_id=release.other.id,
        city="Sài Gòn",
    )

    rows = await _query(integration_session, release)
    assert [row.id for row in rows] == [active_fact.id]

    # Promoting the other release flips which row is readable — the reader follows
    # the project's active version instead of matching on any row.
    release.project.active_kb_version_id = release.other.id
    await integration_session.flush()
    rows = await _query(integration_session, release)
    assert [row.payload["city"] for row in rows] == ["Sài Gòn"]


async def test_query_active_structured_facts_filters_on_the_requested_project(
    integration_session: AsyncSession,
) -> None:
    release = await _seed_release(integration_session)
    fact = await _fact(
        integration_session,
        release=release,
        project_id=release.project.id,
        kb_version_id=release.active.id,
        city="Hải Phòng",
    )
    # A fact that carries another project's id but the same KB version must not leak.
    stranger = await _fact(
        integration_session,
        release=release,
        project_id=(await _seed_release(integration_session)).project.id,
        kb_version_id=release.active.id,
        city="Cần Thơ",
    )

    rows = await _query(integration_session, release)
    assert [row.id for row in rows] == [fact.id]
    assert stranger.id not in {row.id for row in rows}


async def _seed_job(db: AsyncSession, release: _Release, *, title: str) -> Job:
    company = Company(project_id=release.project.id, name=f"Co-{uuid.uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, title=title)
    db.add(job)
    await db.flush()
    return job


def _location(*, job_id: uuid.UUID, kb_version_id: uuid.UUID | None, locality: str) -> JobLocation:
    return JobLocation(
        job_id=job_id,
        kb_version_id=kb_version_id,
        locality=locality,
        status=PublishedStatus.PUBLISHED.value,
        created_at=NOW,
        updated_at=NOW,
    )


def _requirement(
    *, job_id: uuid.UUID, kb_version_id: uuid.UUID | None, text: str
) -> JobRequirement:
    return JobRequirement(
        job_id=job_id,
        kb_version_id=kb_version_id,
        requirement_text=text,
        status=PublishedStatus.PUBLISHED.value,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_job_locations_prefer_the_active_release_then_fall_back_to_legacy(
    integration_session: AsyncSession,
) -> None:
    release = await _seed_release(integration_session)
    job = await _seed_job(integration_session, release, title="Operator")
    integration_session.add_all(
        [
            _location(job_id=job.id, kb_version_id=release.active.id, locality="Hải Phòng"),
            _location(job_id=job.id, kb_version_id=None, locality="legacy"),
            _location(job_id=job.id, kb_version_id=release.other.id, locality="superseded"),
        ]
    )
    legacy_only = await _seed_job(integration_session, release, title="Legacy operator")
    integration_session.add(
        _location(job_id=legacy_only.id, kb_version_id=None, locality="legacy only")
    )
    superseded_only = await _seed_job(integration_session, release, title="Superseded operator")
    integration_session.add(
        _location(job_id=superseded_only.id, kb_version_id=release.other.id, locality="superseded")
    )
    await integration_session.flush()

    with_active = await get_job_locations(
        integration_session,
        job_id=str(job.id),
        active_kb_version_id=str(release.active.id),
    )
    assert [row["locality"] for row in with_active.data] == ["Hải Phòng"]

    fallback = await get_job_locations(
        integration_session,
        job_id=str(legacy_only.id),
        active_kb_version_id=str(release.active.id),
    )
    assert [row["locality"] for row in fallback.data] == ["legacy only"]

    # No active release in scope reads legacy unversioned rows, not NULL-compared rows.
    no_active = await get_job_locations(integration_session, job_id=str(legacy_only.id))
    assert [row["locality"] for row in no_active.data] == ["legacy only"]

    superseded = await get_job_locations(
        integration_session,
        job_id=str(superseded_only.id),
        active_kb_version_id=str(release.active.id),
    )
    assert superseded.found is False


async def test_job_requirements_read_legacy_rows_without_an_active_release(
    integration_session: AsyncSession,
) -> None:
    release = await _seed_release(integration_session)
    job = await _seed_job(integration_session, release, title="Operator")
    integration_session.add_all(
        [
            _requirement(job_id=job.id, kb_version_id=release.active.id, text="active release"),
            _requirement(job_id=job.id, kb_version_id=None, text="legacy unversioned"),
        ]
    )
    await integration_session.flush()

    versioned = await get_job_requirements(
        integration_session,
        job_id=str(job.id),
        active_kb_version_id=str(release.active.id),
    )
    assert [row["text"] for row in versioned.data] == ["active release"]

    # Requirements must not silently disappear when no release is in scope.
    legacy = await get_job_requirements(integration_session, job_id=str(job.id))
    assert legacy.found is True
    assert [row["text"] for row in legacy.data] == ["legacy unversioned"]
