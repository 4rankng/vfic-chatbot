"""Structured Job↔Lead recommendation repository (DB layer).

Two-stage ranker over the existing ``jobs`` table — no new tables, no migrations:

* Stage 1 (SQL WHERE): hard business filters — ACTIVE status, salary band overlap,
  vacancy > 0, optional province / age / gender gates.
* Stage 2 (Python, :mod:`.scoring`): weighted scoring + matched reasons.

All data columns already exist on ``jobs`` (``job.py``); this module only reads them.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import JobStatus
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
        try:
            result = await self.db.execute(_MATCH_SQL, params)
            rows = [dict(r._mapping) for r in result.fetchall()]
        except Exception:
            logger.warning("recommendation match_jobs query failed", exc_info=True)
            return []

        scored = [score_job(lead, JobCandidate.from_row(row)) for row in rows]
        scored.sort(key=lambda s: (-s.score, s.job.title))
        return scored[: max(1, min(top_k, 10))]
