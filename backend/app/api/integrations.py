"""Admin integration settings routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.integrations import (
    MinimaxIntegrationSettingsOut,
    MinimaxIntegrationSettingsUpdate,
    MinimaxIntegrationTestOut,
    OpenRouterIntegrationSettingsOut,
    OpenRouterIntegrationSettingsUpdate,
    OpenRouterIntegrationTestOut,
    ZaloChannelTestOut,
    ZaloIntegrationSettingsOut,
    ZaloIntegrationSettingsUpdate,
)
from app.services.integration_settings import IntegrationSettingsService
from app.services.zalo_bot_service import ZaloBotAdminClient, SendResult
from app.services.zalo_oa_service import ZaloOASender

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])


def _safe_probe_error(prefix: str, result: SendResult, secrets: list[str]) -> str:
    message = result.error or "unknown error"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    if len(message) > 240:
        message = f"{message[:237]}..."
    return f"{prefix}: {message}"


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


@router.post("/zalo/bot/test", response_model=ZaloChannelTestOut)
async def test_zalo_bot(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloChannelTestOut:
    """Probe ONLY the Zalo Bot Platform channel (bot-api.zaloplatforms.com).

    Hits ``getMe`` with the configured bot token. Independent of the OA channel.
    """
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_zalo()
    missing = [] if cfg.bot_token else ["zalo_bot_token"]
    configured = bool(cfg.bot_token)
    connected = False
    errors: list[str] = []
    if configured:
        bot_settings = settings_service.settings.model_copy(
            update={"zalo_bot_token": cfg.bot_token}
        )
        result = await ZaloBotAdminClient(settings=bot_settings).get_me()
        connected = result.ok
        if not result.ok:
            errors.append(_safe_probe_error("zalo_bot", result, [cfg.bot_token]))
    return ZaloChannelTestOut(
        configured=configured,
        connected=connected,
        missing=missing,
        errors=errors,
    )


@router.post("/zalo/oa/test", response_model=ZaloChannelTestOut)
async def test_zalo_oa(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloChannelTestOut:
    """Probe ONLY the Zalo Official Account channel (openapi.zalo.me).

    Hits ``getoa`` with the configured OA access token. Independent of the Bot
    Platform channel.
    """
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_zalo()
    missing = [
        key
        for key, value in (
            ("zalo_oa_app_id", cfg.oa_app_id),
            ("zalo_oa_secret_key", cfg.oa_secret_key),
            ("zalo_oa_access_token", cfg.oa_access_token),
            ("zalo_oa_refresh_token", cfg.oa_refresh_token),
        )
        if not value
    ]
    configured = not missing
    connected = False
    errors: list[str] = []
    if configured:
        result = await ZaloOASender(
            settings=settings_service.settings,
            access_token=cfg.oa_access_token,
        ).get_oa_info()
        connected = result.ok
        if not result.ok:
            errors.append(
                _safe_probe_error(
                    "zalo_oa",
                    result,
                    [cfg.oa_access_token, cfg.oa_refresh_token, cfg.oa_secret_key],
                )
            )
    return ZaloChannelTestOut(
        configured=configured,
        connected=connected,
        missing=missing,
        errors=errors,
    )


@router.get("/minimax", response_model=MinimaxIntegrationSettingsOut)
async def get_minimax_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MinimaxIntegrationSettingsOut:
    return MinimaxIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_minimax_view()
    )


@router.put("/minimax", response_model=MinimaxIntegrationSettingsOut)
async def update_minimax_integration_settings(
    body: MinimaxIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MinimaxIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_minimax(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return MinimaxIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_minimax_view()
    )


@router.post("/minimax/test", response_model=MinimaxIntegrationTestOut)
async def test_minimax_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MinimaxIntegrationTestOut:
    cfg = await IntegrationSettingsService(db).resolve_minimax()
    missing = []
    if not cfg.api_key:
        missing.append("minimax_api_key")
    return MinimaxIntegrationTestOut(
        configured=bool(cfg.api_key),
        missing=missing,
    )


@router.get("/openrouter", response_model=OpenRouterIntegrationSettingsOut)
async def get_openrouter_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OpenRouterIntegrationSettingsOut:
    return OpenRouterIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_openrouter_view()
    )


@router.put("/openrouter", response_model=OpenRouterIntegrationSettingsOut)
async def update_openrouter_integration_settings(
    body: OpenRouterIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OpenRouterIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_openrouter(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return OpenRouterIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_openrouter_view()
    )


@router.post("/openrouter/test", response_model=OpenRouterIntegrationTestOut)
async def test_openrouter_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OpenRouterIntegrationTestOut:
    cfg = await IntegrationSettingsService(db).resolve_openrouter()
    missing = []
    if not cfg.api_key:
        missing.append("openrouter_api_key")
    return OpenRouterIntegrationTestOut(
        configured=bool(cfg.api_key),
        missing=missing,
    )
