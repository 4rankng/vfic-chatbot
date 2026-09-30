"""Project income summaries for the agent's cross-project comparisons."""

from app.recruitment.domain.recommendation import (
    ActiveProjectIncomeSummary,
    IncomeFeatureEvidence,
)
from app.services.recommendation.repository import RecommendationRepository

__all__ = [
    "ActiveProjectIncomeSummary",
    "IncomeFeatureEvidence",
    "RecommendationRepository",
]
