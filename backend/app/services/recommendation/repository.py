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
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
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

    async def find_active_jobs(self, query: str, *, top_k: int = 3) -> ActiveJobLookup:
        """Find currently open jobs for an explicit vacancy-existence question.

        This is intentionally separate from profile-based recommendations: no lead
        data is required, and database failures remain distinguishable from a genuine
        no-match result.
        """
        try:
            rows = (
                await self.db.execute(
                    select(Job, Company.name)
                    .join(Company, Job.company_id == Company.id)
                    .where(
                        Job.status == JobStatus.ACTIVE,
                        func.coalesce(Job.vacancy_count, 0) > 0,
                    )
                    .order_by(Job.updated_at.desc())
                    .limit(self.CANDIDATE_LIMIT)
                )
            ).all()
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
            )
            for job, company_name in rows
        ]
        return select_matching_active_jobs(query, jobs, top_k=top_k)


LeadRecommendationStatus = Literal["matched", "no_match", "insufficient_profile", "unavailable"]


@dataclass(frozen=True)
class LeadJobRecommendation:
    """Typed profile-based recommendation outcome for the graph tool."""

    status: LeadRecommendationStatus
    jobs: tuple[ScoredJob, ...] = ()
