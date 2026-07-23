"""Compatibility wrapper over pure active-opportunity lookup policies."""

from __future__ import annotations

from app.recruitment.domain import recommendation as recommendation_domain

ActiveJob = recommendation_domain.ActiveJob
ActiveJobLookup = recommendation_domain.ActiveJobLookup
ActiveJobLookupStatus = recommendation_domain.ActiveJobLookupStatus
SortBy = recommendation_domain.SortBy
select_matching_active_jobs = recommendation_domain.select_matching_active_jobs
