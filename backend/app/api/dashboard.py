"""Dashboard API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user
from app.identity.application.http import AuthenticatedUser
from app.schemas.dashboard import AttentionDashboardOut
from app.schemas.job import DashboardMetrics
from app.shared.infrastructure.db import get_request_db
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
async def metrics(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> DashboardMetrics:
    """Viewer-scoped dashboard counters (admin = global, recruiter = assigned).

    Window semantics: bot-run aggregates (``bot_run_count``, ``bot_sent_count``,
    ``bot_suppressed_count``, ``bot_success_rate``, ``bot_suppression_rate``,
    ``avg_bot_response_seconds``) cover the LAST 24 HOURS;
    ``p95_bot_response_seconds`` covers the last 7 days.
    Lead/conversation/follow-up counters are current-state, not windowed. Field
    names intentionally unchanged — see the schema for the full contract.
    """
    return await DashboardService(db).metrics(user)


@router.get("/attention", response_model=AttentionDashboardOut)
async def attention(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> AttentionDashboardOut:
    """Recruiter attention dashboard: exact counters + bounded queues (current-state, not windowed)."""
    return await DashboardService(db).attention(user)
