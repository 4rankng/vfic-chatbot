"""Dashboard API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.job import DashboardMetrics
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
async def metrics(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> DashboardMetrics:
    return await DashboardService(db).metrics(user)
