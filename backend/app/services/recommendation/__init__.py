"""Structured Job↔Lead recommendation engine.

Two-stage ranker over the existing ``jobs`` table (no new tables, no migrations):

* Stage 1 — hard SQL filters (ACTIVE status, vacancy > 0, optional province gate)
* Stage 2 — weighted Python scoring (:mod:`.scoring`) with matched reasons

Mirrors the research (MiniMax §7.2 hybrid scoring, Google two-stage retrieve+rank,
ChatGPT "machine-readable matched reasons") on the data columns VFIC already has.
"""

from app.services.recommendation.repository import RecommendationRepository
from app.services.recommendation.scoring import (
    JobCandidate,
    LeadProfile,
    ScoredJob,
    parse_salary_band,
    score_job,
)

__all__ = [
    "RecommendationRepository",
    "JobCandidate",
    "LeadProfile",
    "ScoredJob",
    "parse_salary_band",
    "score_job",
]
