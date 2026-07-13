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
    """Full diagnostic of the Zalo OA channel — checks 4 layers:

    1. All credentials configured (app_id, secret_key, access_token, refresh_token)
    2. Access token valid (getoa probe) — if expired, tries auto-refresh
    3. Secret key valid (refresh probe) — the most common silent failure
    4. Token refresh works (calls oauth.zaloapp.com/v4/oa/access_token)

    Returns granular diagnostics so the admin knows exactly which credential
    is broken, instead of a generic "not connected" with no actionable info.
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
    oa_secret_valid: bool | None = None
    oa_refresh_ok: bool | None = None
    oa_token_expired: bool | None = None

    if configured:
        # Layer 1: probe access token
        result = await ZaloOASender(
            settings=settings_service.settings,
            access_token=cfg.oa_access_token,
            refresh=settings_service.refresh_oa_access_token,
        ).get_oa_info()
        connected = result.ok

        if result.ok:
            # Access token works — but also check if the secret key is valid
            # (it's needed for refresh, which will be needed when the token expires)
            oa_token_expired = False
        else:
            # Access token failed — check if it's expired
            err_text = _safe_probe_error(
                "zalo_oa",
                result,
                [cfg.oa_access_token, cfg.oa_refresh_token, cfg.oa_secret_key],
            )
            is_expired = "expired" in err_text.lower() or "-216" in err_text
            oa_token_expired = is_expired

            if is_expired:
                # Layer 2: try the refresh flow
                new_token = await settings_service.refresh_oa_access_token()
                if new_token:
                    oa_refresh_ok = True
                    # Re-probe with the refreshed token
                    result2 = await ZaloOASender(
                        settings=settings_service.settings,
                        access_token=new_token,
                        refresh=settings_service.refresh_oa_access_token,
                    ).get_oa_info()
                    connected = result2.ok
                    if not result2.ok:
                        errors.append(
                            "Token refreshed but still fails: "
                            + _safe_probe_error("zalo_oa", result2, [new_token])
                        )
                else:
                    oa_refresh_ok = False
                    # Layer 3: diagnose WHY refresh failed — test the secret key directly.
                    # Reuse the process-scoped OA-token diagnostic client (Tech-Lead
                    # Directive §4) — a different oauth host from the runtime refresh,
                    # so a distinct name. Per-request secret_key header (admin-entered).
                    from app.core.http import get_http_client

                    try:
                        client = await get_http_client("zalo_oa_oauth_diag", timeout=10)
                        resp = await client.post(
                            "https://oauth.zaloapp.com/v4/oa/access_token",
                            data={
                                "grant_type": "refresh_token",
                                "refresh_token": cfg.oa_refresh_token,
                                "app_id": cfg.oa_app_id,
                            },
                            headers={"secret_key": cfg.oa_secret_key} if cfg.oa_secret_key else {},
                        )
                        data = resp.json()
                        if isinstance(data, dict) and "access_token" in data:
                            oa_secret_valid = True
                            errors.append(
                                "Secret key valid but refresh returned no token — check app_id"
                            )
                        elif isinstance(data, dict) and data.get("error") == -14004:
                            oa_secret_valid = False
                            errors.append(
                                "❌ OA Secret Key is INVALID — refresh cannot work. Update it from the Zalo OA dashboard."
                            )
                        else:
                            oa_secret_valid = False
                            errors.append(
                                f"Refresh failed: {data.get('error_name', 'unknown')} "
                                f"({data.get('error', '?')}) — {data.get('error_description', '')}"
                            )
                    except Exception as exc:
                        oa_secret_valid = None
                        errors.append(f"Refresh check failed: {exc}")
            else:
                errors.append(err_text)

    return ZaloChannelTestOut(
        configured=configured,
        connected=connected,
        missing=missing,
        errors=errors,
        oa_secret_valid=oa_secret_valid,
        oa_refresh_ok=oa_refresh_ok,
        oa_token_expired=oa_token_expired,
    )


@router.post("/zalo/oa/verify-signature", response_model=ZaloOaSignatureVerifyOut)
async def verify_zalo_oa_signature(
    body: ZaloOaSignatureVerifyRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloOaSignatureVerifyOut:
    """Verify a captured Zalo OA webhook event against the stored Webhook Secret.

    Lets an admin confirm the configured Webhook Secret is the value Zalo actually
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
            detail="Webhook Secret hoặc Zalo App ID chưa được cấu hình.",
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
            "Chữ ký khớp — Webhook Secret đúng."
            if result.verified
            else "Chữ ký không khớp — Webhook Secret có thể sai, "
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
