"""Admin integration settings routes."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.config import ZALO_BOT_WEBHOOK_URL
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
    ZaloOaSignatureVerifyOut,
    ZaloOaSignatureVerifyRequest,
)
from app.services.integration_settings import (
    IntegrationSettingsService,
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
)
from app.services.zalo_bot_service import ZaloBotAdminClient, SendResult
from app.services.zalo_oa_service import ZaloOASender
from app.services.zalo_oa_signature import verify_signature

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])


def _safe_probe_error(prefix: str, result: SendResult, secrets: list[str]) -> str:
    message = result.error or "unknown error"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    if len(message) > 240:
        message = f"{message[:237]}..."
    return f"{prefix}: {message}"


def _bot_admin_client(settings_service, cfg) -> ZaloBotAdminClient:
    """Build an admin client using the resolved (DB-precedence) bot token."""
    bot_settings = settings_service.settings.model_copy(update={"zalo_bot_token": cfg.bot_token})
    return ZaloBotAdminClient(settings=bot_settings)


async def _sync_bot_webhook(
    settings_service: IntegrationSettingsService, changed: list[str]
) -> dict:
    """Best-effort: push the saved Bot webhook secret to Zalo via setWebhook.

    Saving the webhook secret in the CRM updates only the app side; Zalo keeps
    sending the old secret_token until ``setWebhook`` re-registers it, and a
    mismatch silently 401-drops every inbound. Re-running on every save would
    be needless Zalo traffic, so this only fires when the bot token or webhook
    secret was just changed. Non-blocking: a failure is surfaced as an error
    status and never raises — the DB save has already committed.
    """
    if not (set(changed) & {ZALO_BOT_TOKEN, ZALO_BOT_WEBHOOK_SECRET}):
        return {"synced": False, "skipped": "no bot token or webhook secret change"}
    cfg = await settings_service.resolve_zalo()
    if not cfg.bot_token or not cfg.bot_webhook_secret:
        return {"synced": False, "skipped": "bot token or webhook secret not configured"}
    url = ZALO_BOT_WEBHOOK_URL
    result = await _bot_admin_client(settings_service, cfg).set_webhook(url, cfg.bot_webhook_secret)
    if result.ok:
        return {"synced": True, "url": url}
    return {
        "synced": False,
        "url": url,
        "error": _safe_probe_error("setWebhook", result, [cfg.bot_token]),
    }


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
    settings_service = IntegrationSettingsService(db)
    changed = await settings_service.update_zalo(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    view = await settings_service.admin_view()
    # Push the just-saved webhook secret to Zalo so both sides match. Saving
    # alone updates only the app side; a mismatch silently 401-drops all
    # inbound. Best-effort: the DB write is already committed.
    view["zalo_bot_webhook_sync"] = await _sync_bot_webhook(settings_service, changed)
    return ZaloIntegrationSettingsOut.model_validate(view)


@router.post("/zalo/bot/test", response_model=ZaloChannelTestOut)
async def test_zalo_bot(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloChannelTestOut:
    """Probe ONLY the Zalo Bot Platform channel (bot-api.zaloplatforms.com).

    Hits ``getMe`` with the configured bot token, and — when that succeeds —
    ``getWebhookInfo`` to confirm a webhook URL is registered. Independent of
    the OA channel. Zalo never returns the registered secret_token, so a
    registered URL does not prove the secret matches — only a real inbound does.
    """
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_zalo()
    missing = [] if cfg.bot_token else ["zalo_bot_token"]
    configured = bool(cfg.bot_token)
    connected = False
    errors: list[str] = []
    webhook_registered: bool | None = None
    webhook_url: str | None = None
    if configured:
        client = _bot_admin_client(settings_service, cfg)
        result = await client.get_me()
        connected = result.ok
        if not result.ok:
            errors.append(_safe_probe_error("zalo_bot", result, [cfg.bot_token]))
        else:
            info = await client.get_webhook_info()
            if info.ok and isinstance(info.raw, dict):
                webhook_url = (info.raw.get("result") or {}).get("url") or None
            else:
                errors.append(_safe_probe_error("getWebhookInfo", info, [cfg.bot_token]))
            webhook_registered = bool(webhook_url)
    return ZaloChannelTestOut(
        configured=configured,
        connected=connected,
        missing=missing,
        errors=errors,
        webhook_registered=webhook_registered,
        webhook_url=webhook_url,
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


@router.post("/zalo/oa/verify-signature", response_model=ZaloOaSignatureVerifyOut)
async def verify_zalo_oa_signature(
    body: ZaloOaSignatureVerifyRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloOaSignatureVerifyOut:
    """Verify a captured Zalo OA webhook event against the stored OA Secret Key.

    Lets an admin confirm the configured OA Secret Key is the value Zalo actually
    signs with, by pasting a real event's ``X-ZEvent-Signature`` + raw body +
    ``X-ZEvent-Timestamp`` (from the Zalo console test or server logs). The live
    Test Connection probe authenticates with the access_token and cannot detect a
    wrong secret; this deterministic check can.
    """
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_zalo()
    secret_configured = bool(cfg.oa_secret_key)
    app_id_configured = bool(cfg.oa_app_id)
    if not secret_configured or not app_id_configured:
        return ZaloOaSignatureVerifyOut(
            verified=False,
            secret_configured=secret_configured,
            app_id_configured=app_id_configured,
            matched_label=None,
            detail="OA Secret Key hoặc App ID chưa được cấu hình.",
        )
    try:
        payload = json.loads(body.raw_body)
    except json.JSONDecodeError:
        return ZaloOaSignatureVerifyOut(
            verified=False,
            secret_configured=True,
            app_id_configured=True,
            matched_label=None,
            detail="Body không phải JSON hợp lệ — dán nguyên văn (raw) body Zalo gửi.",
        )
    result = verify_signature(
        signature=body.signature,
        raw=body.raw_body.encode("utf-8"),
        payload=payload,
        app_id=cfg.oa_app_id,
        secret_key=cfg.oa_secret_key,
        timestamp_header=body.timestamp,
    )
    return ZaloOaSignatureVerifyOut(
        verified=result.verified,
        secret_configured=True,
        app_id_configured=True,
        matched_label=result.matched_label,
        detail=(
            "Chữ ký khớp — OA Secret Key đúng."
            if result.verified
            else "Chữ ký không khớp — OA Secret Key có thể sai (khác App Secret), "
            "hoặc body/timestamp không khớp nguyên văn byte-for-byte."
        ),
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
