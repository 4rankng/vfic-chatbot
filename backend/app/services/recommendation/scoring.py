"""Compatibility wrapper over pure recruitment recommendation policies."""

from __future__ import annotations

from app.core.config import get_settings
from app.recruitment.domain import recommendation as recommendation_domain

JobCandidate = recommendation_domain.JobCandidate
LeadProfile = recommendation_domain.LeadProfile
ScoredJob = recommendation_domain.ScoredJob
parse_salary_band = recommendation_domain.parse_salary_band
score_experience = recommendation_domain.score_experience
score_location = recommendation_domain.score_location
score_salary = recommendation_domain.score_salary
score_support_flags = recommendation_domain.score_support_flags
score_title = recommendation_domain.score_title


def score_job(lead: LeadProfile, job: JobCandidate) -> ScoredJob:
    """Apply the weighted structured recommendation formula."""
    settings = get_settings()
    return recommendation_domain.score_job(
        lead,
        job,
        weights=recommendation_domain.RecommendationWeights(
            title=getattr(settings, "rec_weight_title", 0.35),
            salary=getattr(settings, "rec_weight_salary", 0.25),
            location=getattr(settings, "rec_weight_location", 0.20),
            support=getattr(settings, "rec_weight_support", 0.10),
            experience=getattr(settings, "rec_weight_experience", 0.10),
        ),
    )
