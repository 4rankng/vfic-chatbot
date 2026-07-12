"""Dashboard API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.dashboard import AttentionDashboardOut
from app.schemas.job import DashboardMetrics
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
async def metrics(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DashboardMetrics:
    return await DashboardService(db).metrics(user)


@router.get("/attention", response_model=AttentionDashboardOut)
async def attention(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AttentionDashboardOut:
    return await DashboardService(db).attention(user)
