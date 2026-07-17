"""Structured Job↔Lead recommendation repository (DB layer).

Two-stage ranker over the existing ``jobs`` table — no new tables, no migrations:

* Stage 1 (SQL WHERE): hard business filters — ACTIVE status, salary band overlap,
  vacancy > 0, optional province / age / gender gates.
* Stage 2 (Python, :mod:`.scoring`): weighted scoring + matched reasons.

All data columns already exist on ``jobs`` (``job.py``); this module only reads them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.job import Job
from app.models.job import JobStatus
from app.services.recommendation.availability import (
    ActiveJob,
    ActiveJobLookup,
    select_matching_active_jobs,
)
from app.services.recommendation.scoring import JobCandidate, LeadProfile, ScoredJob, score_job

logger = logging.getLogger(__name__)

# Stage-1 candidate fetch. Filters are deliberately loose (status + vacancy) so the
# Python scorer can weigh the rest; tightening here risks dropping jobs that fail a
# soft signal (e.g. age) but pass everything else. Optional province filter is the
# one hard location gate — a candidate saying "Bình Dương" should never see Hà Nội.
_MATCH_SQL = text(
    """
    SELECT
        j.id, j.title, j.factory_name, j.province, j.district,
        j.salary_min, j.salary_max, j.shift,
        j.age_min, j.age_max, j.gender_requirement,
        j.experience_required,
        j.accommodation_support, j.meal_support, j.transport_support,
        j.vacancy_count
    FROM jobs j
    WHERE j.status = :status
      AND COALESCE(j.vacancy_count, 0) > 0
      AND (:province IS NULL
           OR normalize_search_text(j.province) ILIKE normalize_search_text(:province)
           OR normalize_search_text(j.district) ILIKE normalize_search_text(:province))
    ORDER BY j.updated_at DESC
    LIMIT :limit
    """
)


class RecommendationRepository:
    """Read-only structured job matching against a candidate lead profile."""

    CANDIDATE_LIMIT = 100  # Stage-1 fetch ceiling; scorer truncates to top_k.

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def match_jobs(
        self,
        lead: LeadProfile,
        *,
        top_k: int = 5,
        province: str | None = None,
    ) -> list[ScoredJob]:
        """Return up to ``top_k`` ACTIVE jobs ranked by fit against the lead.

        ``province`` forces a hard location gate (recommended when the lead states one);
        pass ``None`` to search nationwide (cold start with no location signal).
        """
        gate = province or lead.living_area or lead.region or None
        params: dict[str, Any] = {
            "status": JobStatus.ACTIVE.value,
            "province": gate,
            "limit": self.CANDIDATE_LIMIT,
        }
        result = await self.db.execute(_MATCH_SQL, params)
        rows = [dict(r._mapping) for r in result.fetchall()]

        scored = [score_job(lead, JobCandidate.from_row(row)) for row in rows]
        scored.sort(key=lambda s: (-s.score, s.job.title))
        return scored[: max(1, min(top_k, 10))]

    async def list_active_jobs(
        self,
        *,
        role: str | None = None,
        company: str | None = None,
        location: str | None = None,
        top_k: int = 3,
        project_ids: Sequence[str] | None = None,
    ) -> ActiveJobLookup:
        """List scoped open jobs satisfying explicit semantic filters.

        This is intentionally separate from profile-based recommendations: no lead
        data is required. An empty/unconfigured catalog, a genuine no-match, and a
        database failure remain distinct so the graph can choose the right authority.
        """
        if project_ids == []:
            return ActiveJobLookup("catalog_empty")
        try:
            predicates = [
                Job.status == JobStatus.ACTIVE,
                func.coalesce(Job.vacancy_count, 0) > 0,
                Project.is_active.is_(True),
            ]
            if project_ids is not None:
                predicates.append(Company.project_id.in_(project_ids))
            rows = (
                await self.db.execute(
                    select(Job, Company.name, Company.aliases, Project.name, Project.slug)
                    .join(Company, Job.company_id == Company.id)
                    .join(Project, Company.project_id == Project.id)
                    .where(*predicates)
                    .order_by(Job.updated_at.desc(), Job.id.asc())
                    .limit(self.CANDIDATE_LIMIT)
                )
            ).all()
            if not rows:
                catalog_query = (
                    select(Job.id)
                    .join(Company, Job.company_id == Company.id)
                    .join(Project, Company.project_id == Project.id)
                    .where(Project.is_active.is_(True))
                )
                if project_ids is not None:
                    catalog_query = catalog_query.where(Company.project_id.in_(project_ids))
                catalog_probe = await self.db.execute(
                    catalog_query.limit(1)
                )
                if catalog_probe.scalar_one_or_none() is not None:
                    return ActiveJobLookup("no_match")
                return ActiveJobLookup("catalog_empty")
        except Exception:
            logger.warning("active-job availability lookup failed", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:  # noqa: BLE001 — preserve the candidate-facing unavailable reply
                logger.debug("active-job availability rollback failed", exc_info=True)
            return ActiveJobLookup("unavailable")

        jobs = [
            ActiveJob(
                id=str(job.id),
                title=job.title,
                company_name=str(company_name),
                factory_name=job.factory_name or "",
                province=job.province or "",
                district=job.district or "",
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                vacancy_count=job.vacancy_count,
                company_aliases=tuple(company_aliases or ()),
                project_name=str(project_name or ""),
                project_slug=str(project_slug or ""),
                address=str(getattr(job, "address", "") or ""),
                shift=str(getattr(job, "shift", "") or ""),
                gender_requirement=str(getattr(job, "gender_requirement", "") or ""),
                age_min=getattr(job, "age_min", None),
                age_max=getattr(job, "age_max", None),
                experience_required=str(getattr(job, "experience_required", "") or ""),
                accommodation_support=getattr(job, "accommodation_support", None),
                meal_support=getattr(job, "meal_support", None),
                transport_support=getattr(job, "transport_support", None),
                description=str(getattr(job, "description", "") or ""),
                requirements=str(getattr(job, "requirements", "") or ""),
                benefits=str(getattr(job, "benefits", "") or ""),
            )
            for job, company_name, company_aliases, project_name, project_slug in rows
        ]
        return select_matching_active_jobs(
            jobs,
            role=role,
            company=company,
            location=location,
            top_k=top_k,
        )


LeadRecommendationStatus = Literal["matched", "no_match", "insufficient_profile", "unavailable"]


@dataclass(frozen=True)
class LeadJobRecommendation:
    """Typed profile-based recommendation outcome for the graph tool."""

    status: LeadRecommendationStatus
    jobs: tuple[ScoredJob, ...] = ()
