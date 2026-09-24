"""Zalo channel diagnostics: Bot + OA probes and the webhook-sync policy.

Extracted from the admin integrations router so the probes (including the
diagnostic OAuth token POST) are exercisable without HTTP. The raw POST
reuses the process-scoped integration HTTP client, preserving the exact wire
shape (form-encoded body, per-request ``secret_key`` header) the endpoint
used.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.admin_runtime import (
    ZALO_BOT_WEBHOOK_URL,
    get_integration_http_client,
)
from app.schemas.integrations import ZaloChannelTestOut
from app.services.integration_settings import (
    IntegrationSettingsService,
    ZALO_BOT_TOKEN,
    ZALO_BOT_WEBHOOK_SECRET,
)
from app.services.zalo_bot_service import ZaloBotAdminClient, SendResult
from app.services.zalo_oa_service import ZaloOASender


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


async def sync_bot_webhook(
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


async def probe_zalo_bot_channel(db: AsyncSession) -> ZaloChannelTestOut:
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


async def probe_zalo_oa_channel(db: AsyncSession) -> ZaloChannelTestOut:
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
                    try:
                        client = await get_integration_http_client(
                            "zalo_oa_oauth_diag", timeout=10
                        )
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
