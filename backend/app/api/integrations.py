"""Admin integration settings routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.integrations import (
    ZaloIntegrationSettingsOut,
    ZaloIntegrationSettingsUpdate,
    ZaloIntegrationTestOut,
)
from app.services.integration_settings import IntegrationSettingsService

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])


@router.get("/zalo", response_model=ZaloIntegrationSettingsOut)
async def get_zalo_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloIntegrationSettingsOut:
    return ZaloIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_view()
    )


@router.put("/zalo", response_model=ZaloIntegrationSettingsOut)
async def update_zalo_integration_settings(
    body: ZaloIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_zalo(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return ZaloIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_view()
    )


@router.post("/zalo/test", response_model=ZaloIntegrationTestOut)
async def test_zalo_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloIntegrationTestOut:
    cfg = await IntegrationSettingsService(db).resolve_zalo()
    missing = []
    if not cfg.bot_token:
        missing.append("zalo_bot_token")
    if not cfg.oa_app_id:
        missing.append("zalo_oa_app_id")
    if not cfg.oa_secret_key:
        missing.append("zalo_oa_secret_key")
    if not cfg.oa_access_token:
        missing.append("zalo_oa_access_token")
    return ZaloIntegrationTestOut(
        bot_configured=bool(cfg.bot_token),
        oa_configured=bool(cfg.oa_app_id and cfg.oa_secret_key and cfg.oa_access_token),
        missing=missing,
    )
