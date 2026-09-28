"""Zalo channel diagnostics: Bot + OA probes and the webhook-sync policy.

Extracted from the admin integrations router so the probes are exercisable
without HTTP. Nothing here redeems a credential: the probes read stored values
and call Zalo's read APIs, and the one token grant they trigger is delegated to
``IntegrationSettingsService.refresh_oa_access_token`` so the rotated pair is
always persisted (a refresh token is single-use, so a probe that redeemed one
and threw it away would strand the OA).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.admin_runtime import ZALO_BOT_WEBHOOK_URL
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
    """Full diagnostic of the Zalo OA channel — checks 3 layers:

    1. All credentials configured (app_id, secret_key, access_token, refresh_token)
    2. Access token valid (getoa probe)
    3. Token refresh works — delegated to the provider, which redeems the
       single-use grant and persists whatever it is issued. A rejection means
       the stored refresh token is gone and only a fresh authorization fixes
       it, so the probe says so rather than re-redeeming to find out.

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
                    # The refresh grant is single-use, so it must not be
                    # redeemed a second time just to diagnose the secret key:
                    # that discarded a freshly issued pair and left the stored
                    # token dead (the "silent refresh" behind OPS-31). The
                    # provider already logs Zalo's own error fields, so report
                    # the actionable conclusion instead of buying granularity
                    # with the credential. The secret key can no longer be
                    # tested on its own — that needs a fresh token anyway.
                    oa_secret_valid = None
                    errors.append(
                        "Refresh Token bị Zalo từ chối (thường là -14014: token đã "
                        "dùng hoặc hết hạn). Vào OA dashboard Zalo lấy cặp Access "
                        "Token + Refresh Token mới rồi lưu lại."
                    )
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
