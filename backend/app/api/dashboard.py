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
    return await DashboardService(db).metrics(user)


@router.get("/attention", response_model=AttentionDashboardOut)
async def attention(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> AttentionDashboardOut:
    return await DashboardService(db).attention(user)
