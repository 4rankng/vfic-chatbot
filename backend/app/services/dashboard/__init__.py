"""Dashboard domain package: metrics service + its data-access repository."""
from app.services.dashboard.repository import DashboardRepository
from app.services.dashboard.service import DashboardService

__all__ = ["DashboardService", "DashboardRepository"]
