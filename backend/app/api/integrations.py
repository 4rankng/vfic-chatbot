"""Admin integration settings routes."""

import json
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.identity.application.http import AuthenticatedUser as User
from app.integrations.admin_runtime import (
    ZALO_BOT_WEBHOOK_URL,
    get_integration_http_client,
    get_integration_redis,
    get_integration_settings,
    load_enabled_admin,
)
from app.schemas.integrations import (
    FacebookAccountStatusOut,
    FacebookChannelTestOut,
    FacebookCredentialsOut,
    FacebookCredentialsReveal,
    FacebookCredentialsUpdate,
    FacebookIntegrationOut,
    FacebookOAuthCompleteRequest,
    FacebookOAuthStartOut,
    FacebookPageListOut,
    FacebookPageOut,
    FacebookPageProjectAdd,
    FacebookPageProjectAssignmentOut,
    FacebookPageProjectsOut,
    FacebookPageProjectsUpdate,
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
from app.shared.infrastructure.db import get_request_db as get_db

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])

logger = logging.getLogger(__name__)


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


# ─── Facebook / Messenger OAuth lifecycle (Phase 4) ─────────────────────────
#
# Every endpoint except the provider callback is admin-only. The callback is
# authenticated by its one-time state because Meta's browser redirect cannot
# carry the app's Bearer header. Responses carry no tokens, app secrets, or raw
# PSIDs. OAuth state/flow records are Redis-backed, single-use, short-TTL, and
# bound to the initiating admin's id + JWT version. Transient Page-credential
# capsules are encrypted at rest in Redis (never plaintext).
#
# The five-step flow:
#   1. start      → returns the official authorization URL
#   2. callback   → validates state, exchanges code server-side, stores flow
#   3. pages      → returns safe Page summaries for selection
#   4. complete   → selects one Page, probes identity, subscribes, persists
#   5. test/disconnect/GET → status, health probe, disconnect


_FB_OAUTH_STATE_PREFIX = "fb_oauth_state:"
_FB_OAUTH_TTL_SECONDS = 300  # 5 minutes — single-use, short-lived


async def _redis():
    return get_integration_redis()


def _fb_callback_origin() -> str:
    """Return the deployment-owned first allowlisted OAuth origin."""
    settings = get_integration_settings()
    return next(iter(settings.facebook_callback_allowlist or ["http://localhost:5173"])).rstrip("/")


def _fb_callback_url() -> str:
    """The server-side OAuth callback URI. Allowlisted in config."""
    return f"{_fb_callback_origin()}/api/v1/admin/integrations/facebook/oauth/callback"


def _fb_frontend_redirect_url(
    *, status: str, flow_id: str | None = None, error: str | None = None
) -> str:
    """Build the fixed Settings redirect without provider-controlled values."""
    query: dict[str, str] = {"facebook_oauth_status": status}
    if flow_id:
        query["facebook_oauth_flow_id"] = flow_id
    if error:
        query["facebook_oauth_error"] = error
    return f"{_fb_callback_origin()}/#/settings?{urlencode(query)}"


_FB_REDIRECT_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def _fb_oauth_redirect_error(code: str) -> RedirectResponse:
    return RedirectResponse(
        _fb_frontend_redirect_url(status="error", error=code),
        status_code=302,
        headers=_FB_REDIRECT_HEADERS,
    )


async def _facebook_oauth_coordinator():
    from app.integrations.facebook_oauth import (
        FacebookOAuthCoordinator,
        RedisFacebookOAuthFlowStore,
        RedisFacebookOAuthStateStore,
    )

    redis = await _redis()
    return FacebookOAuthCoordinator(
        state_store=RedisFacebookOAuthStateStore(
            redis=redis,
            key_prefix=_FB_OAUTH_STATE_PREFIX,
        ),
        flow_store=RedisFacebookOAuthFlowStore(redis=redis),
        ttl_seconds=_FB_OAUTH_TTL_SECONDS,
        state_factory=lambda: secrets.token_urlsafe(32),
        flow_id_factory=lambda: secrets.token_urlsafe(16),
    )


async def _load_facebook_oauth_flow(*, flow_id: str, admin: User, consume: bool = False):
    """Load a valid OAuth flow owned by this exact authenticated session."""
    from app.integrations.facebook_oauth import FacebookOAuthFlowUnavailable

    coordinator = await _facebook_oauth_coordinator()
    try:
        return await coordinator.load_flow(
            flow_id=flow_id,
            admin_id=admin.id,
            token_version=int(admin.token_version),
            consume=consume,
        )
    except FacebookOAuthFlowUnavailable:
        pass
    raise HTTPException(
        status_code=410,
        detail="Phiên chọn Trang không hợp lệ hoặc đã hết hạn. Vui lòng kết nối lại.",
    )


@router.post("/facebook/oauth/start", response_model=FacebookOAuthStartOut)
async def start_facebook_oauth(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookOAuthStartOut:
    """Begin Facebook Login for Business. Stores single-use state in Redis."""
    from app.channels.providers.facebook_oauth import build_authorization_url

    # Resolve app credentials DB-first (env fallback). A missing app_id would
    # otherwise build an OAuth URL with an empty client_id, which Facebook
    # rejects with a generic "Invalid app ID" page. Surface a clear Vietnamese
    # 400 here so the admin knows to configure credentials first.
    settings_service = IntegrationSettingsService(db)
    oauth_cfg = await settings_service.resolve_facebook_oauth()
    if not oauth_cfg.app_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chưa cấu hình Meta App ID. Vào Cài đặt → Facebook Messenger để "
                "cấu hình thông tin ứng dụng Meta trước khi kết nối."
            ),
        )
    coordinator = await _facebook_oauth_coordinator()
    state = await coordinator.issue_state(
        admin_id=admin.id,
        token_version=int(admin.token_version),
    )
    return FacebookOAuthStartOut(
        authorization_url=build_authorization_url(
            state=state, redirect_uri=_fb_callback_url(), config=oauth_cfg
        )
    )


@router.get("/facebook/oauth/callback")
async def facebook_oauth_callback(
    state: str,
    code: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Validate state, exchange code server-side, store an encrypted flow record.

    Redirects the browser to the frontend with only ``flow_id`` + ``status``;
    no code, token, or Page list crosses to the browser. The flow record stores
    encrypted Page summaries + the user access token (encrypted with the
    integration cipher, never plaintext in Redis).
    """
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        exchange_code_for_user_token,
        list_pages,
    )
    from app.integrations.facebook_oauth import FacebookOAuthInvalidState, FacebookOAuthPage

    coordinator = await _facebook_oauth_coordinator()
    try:
        bound_session = await coordinator.consume_state(state=state)
    except FacebookOAuthInvalidState:
        return _fb_oauth_redirect_error("invalid_state")

    admin = await load_enabled_admin(db, bound_session.admin_id)
    if admin is None:
        return _fb_oauth_redirect_error("invalid_admin")
    if admin.token_version != bound_session.token_version:
        return _fb_oauth_redirect_error("session_changed")
    if not code:
        return _fb_oauth_redirect_error("missing_code")

    try:
        # Resolve app credentials DB-first (env fallback) just before the
        # exchange — the callback may have spent seconds in invalid-state /
        # invalid-admin branches above where the config is not yet needed.
        oauth_cfg = await IntegrationSettingsService(db).resolve_facebook_oauth()
        user_token = await exchange_code_for_user_token(
            code=code, redirect_uri=_fb_callback_url(), config=oauth_cfg
        )
        pages = await list_pages(user_token)
    except (FacebookOAuthError, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "facebook oauth code exchange failed: admin=%s error=%s: %s",
            admin.id,
            type(exc).__name__,
            exc,
        )
        return _fb_oauth_redirect_error("exchange_failed")

    if not pages:
        return _fb_oauth_redirect_error("no_pages")

    flow_id = await coordinator.store_flow(
        admin_id=admin.id,
        token_version=int(admin.token_version),
        user_token=user_token,
        pages=[FacebookOAuthPage(id=p.id, name=p.name) for p in pages],
    )
    return RedirectResponse(
        _fb_frontend_redirect_url(status="pending_selection", flow_id=flow_id),
        status_code=302,
        headers=_FB_REDIRECT_HEADERS,
    )


@router.get("/facebook/oauth/pages", response_model=FacebookPageListOut)
async def list_facebook_pages(
    flow_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageListOut:
    """Return the safe Page list stored in the flow record."""
    from app.channels.providers.facebook_account import FacebookAccountResolver

    payload = await _load_facebook_oauth_flow(
        flow_id=flow_id,
        admin=admin,
    )
    pages = [FacebookPageOut(id=page.id, name=page.name) for page in payload.pages]
    resolver = FacebookAccountResolver(db)
    # Multi-Page: report every currently-active Page, not just one.
    active_page_ids = [
        ref.account_key
        for ref in await resolver.list_facebook_accounts()
        if ref.is_active
    ]
    return FacebookPageListOut(pages=pages, active_page_ids=active_page_ids)


@router.post("/facebook/oauth/complete", response_model=FacebookAccountStatusOut)
async def complete_facebook_oauth(
    payload: FacebookOAuthCompleteRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookAccountStatusOut:
    """Select one Page, obtain Page authority, probe identity, subscribe, persist.

    ``project_ids`` (optional replace-all) is validated BEFORE any Meta-side
    call so an unknown Project fails fast with 422 instead of after the app has
    already subscribed to the Page. The assignment then commits atomically with
    activation (see ``FacebookPageLifecycle.activate_or_reactivate``).
    """
    from app.channels.providers.facebook_account import (
        FacebookPageAssignments,
        FacebookPageAssignmentInvalidError,
        FacebookPageLifecycle,
        FacebookPageUnassignedError,
    )
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        get_page_access_token,
        subscribe_app_to_page,
        unsubscribe_app_from_page,
    )

    project_ids: list[str] | None = None
    if payload.project_ids is not None:
        assignments_service = FacebookPageAssignments(db)
        try:
            validated = await assignments_service.validate_project_ids(
                payload.project_ids
            )
        except FacebookPageAssignmentInvalidError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        project_ids = [str(pid) for pid in validated]

    flow = await _load_facebook_oauth_flow(
        flow_id=payload.flow_id,
        admin=admin,
        consume=True,
    )
    user_token = flow.user_token
    page_name = next(
        (page.name for page in flow.pages if page.id == payload.page_id),
        payload.page_id,
    )

    try:
        # No separate identity probe: the token is read from the /me/accounts
        # entry whose id equals page_id, so it is bound to this Page by
        # construction. Probing it via GET /me would additionally require
        # pages_read_engagement, which this integration does not request.
        # subscribe_app_to_page below still fails closed on an unusable token.
        page_token = await get_page_access_token(user_token, payload.page_id)
        await subscribe_app_to_page(payload.page_id, page_token)
    except (FacebookOAuthError, httpx.HTTPError, ValueError) as exc:
        # Generic Vietnamese error to the client — never echo the Graph
        # response body (it can contain the access token in some malformed-
        # token error shapes). The real cause is logged server-side only.
        logger.warning(
            "facebook page activation failed: admin=%s page_id=%s error=%s: %s",
            admin.id,
            payload.page_id,
            type(exc).__name__,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail="Kích hoạt Trang thất bại. Vui lòng kết nối lại.",
        )

    try:
        lifecycle = FacebookPageLifecycle(db)
        account = await lifecycle.activate_or_reactivate(
            page_id=payload.page_id,
            page_name=page_name,
            page_access_token=page_token,
            admin_id=admin.id,
            project_ids=project_ids,
        )
    except FacebookPageUnassignedError:
        # D1 gate: activation refuses a Page with zero mappings to currently-
        # ACTIVE Projects. The Meta-side subscription DID succeed, so compensate
        # it (best-effort — the 409 must survive a flaky unsubscribe) before
        # surfacing the gate to the operator.
        try:
            await unsubscribe_app_from_page(payload.page_id, page_token)
        except Exception:  # noqa: BLE001 — compensation is best-effort
            pass
        raise HTTPException(
            status_code=409,
            detail=(
                "Trang chưa được gán dự án nào đang hoạt động. "
                "Hãy chọn ít nhất một dự án rồi thử lại."
            ),
        ) from None
    except Exception:
        # The Meta-side subscription succeeded but the DB activation failed
        # (e.g. concurrent activation). Best-effort unsubscribe so we don't
        # leave a Meta-side subscription with no DB counterpart, then re-raise.
        await unsubscribe_app_from_page(payload.page_id, page_token)
        raise
    return FacebookAccountStatusOut(
        page_id=payload.page_id,
        page_id_suffix=payload.page_id[-4:],
        label=page_name,
        status=account.status,
    )


@router.get("/facebook", response_model=FacebookIntegrationOut)
async def get_facebook_status(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookIntegrationOut:
    """Safe status of all Facebook Page accounts (active + archived).

    ``enabled`` mirrors how Zalo Chatbot / Zalo OA are considered configured:
    the channel is on when an admin has connected an active Page (an ACTIVE
    ChannelAccount row exists). It is NOT a deploy-time env toggle.
    """
    from app.channels.providers.facebook_account import FacebookAccountResolver

    resolver = FacebookAccountResolver(db)
    accounts = await resolver.list_facebook_accounts()
    return FacebookIntegrationOut(
        enabled=any(a.is_active for a in accounts),
        accounts=[
            FacebookAccountStatusOut(
                page_id=a.account_key,
                page_id_suffix=(a.account_key[-4:] if a.account_key else ""),
                label=a.label,
                status=a.status,
            )
            for a in accounts
        ],
    )


@router.post("/facebook/test", response_model=FacebookChannelTestOut)
async def test_facebook_connection(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookChannelTestOut:
    """Health probe: resolve the active Page, probe its identity, and verify
    the Meta app is subscribed to the Page for webhook events."""
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        page_is_app_subscribed,
    )
    from app.services.integration_settings import IntegrationSettingsService

    resolver = FacebookAccountResolver(db)
    active = await resolver.active_facebook_page()
    if active is None or not active.is_active:
        return FacebookChannelTestOut(
            healthy=False, error="Chưa có Trang Facebook nào được kết nối."
        )
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_facebook(active.account_key)
    if cfg is None:
        return FacebookChannelTestOut(
            healthy=False, error="Không giải mã được token Trang. Vui lòng kết nối lại."
        )
    # The subscription lookup below doubles as the token check: it is made with
    # the Page token and fails closed when that token is invalid or revoked.
    # A dedicated GET /me identity probe would additionally require
    # pages_read_engagement, which this integration does not request.
    #
    # A valid Page token alone does not prove webhook events arrive: the app
    # must also be subscribed to the Page (Meta or a competing integration on
    # the same Page can drop it). Fail the probe when it is not.
    try:
        subscribed = await page_is_app_subscribed(
            active.account_key, cfg.page_access_token, str(cfg.app_id or "").strip()
        )
    except (FacebookOAuthError, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "facebook page subscription check failed: page_id=%s error=%s: %s",
            active.account_key,
            type(exc).__name__,
            exc,
        )
        return FacebookChannelTestOut(
            healthy=False,
            app_subscribed=None,
            error="Không kiểm tra được đăng ký webhook của ứng dụng trên Trang.",
        )
    if not subscribed:
        return FacebookChannelTestOut(
            healthy=False,
            app_subscribed=False,
            error=(
                "Ứng dụng chưa nhận sự kiện webhook từ Trang này. "
                "Hãy ngắt kết nối rồi kết nối lại Trang."
            ),
        )
    return FacebookChannelTestOut(healthy=True, app_subscribed=True)


@router.get("/facebook/credentials", response_model=FacebookCredentialsOut)
async def get_facebook_credentials(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookCredentialsOut:
    """Safe status of the app-level Meta credentials (configured flag + preview)."""
    return FacebookCredentialsOut.model_validate(
        await IntegrationSettingsService(db).admin_facebook_oauth_view()
    )


@router.post("/facebook/credentials/reveal", response_model=FacebookCredentialsReveal)
async def reveal_facebook_credentials(
    response: Response,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookCredentialsReveal:
    """Return the stored Meta secrets in plaintext to an admin.

    Re-registering the webhook on Meta needs the verify token verbatim. POST
    rather than GET so the response is never cached, prefetched, or replayed
    from browser history; ``no-store`` closes the same gap at the proxy. The
    reveal is audited by actor; the values themselves are never logged.
    """
    cfg = await IntegrationSettingsService(db).resolve_facebook_oauth()
    logger.warning("facebook credentials revealed: admin=%s", admin.id)
    response.headers["Cache-Control"] = "no-store"
    return FacebookCredentialsReveal(
        facebook_app_secret=cfg.app_secret or None,
        facebook_webhook_verify_token=cfg.verify_token or None,
    )


@router.put("/facebook/credentials", response_model=FacebookCredentialsOut)
async def update_facebook_credentials(
    body: FacebookCredentialsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookCredentialsOut:
    """Partial update of the app-level Meta credentials.

    All fields are optional; a missing or empty value leaves the stored value
    unchanged. ``app_secret`` and ``verify_token`` are AES-GCM encrypted at
    rest; ``app_id`` and ``login_config_id`` are stored as plaintext (they
    appear in the browser OAuth URL anyway).
    """
    settings_service = IntegrationSettingsService(db)
    await settings_service.update_facebook_oauth(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return FacebookCredentialsOut.model_validate(await settings_service.admin_facebook_oauth_view())


@router.delete("/facebook", response_model=FacebookAccountStatusOut)
async def disconnect_facebook(
    page_id: str | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookAccountStatusOut:
    """Mark a Page inactive. Never deletes contacts/conversations/history.

    ``page_id`` (optional query param) disconnects one specific Page — the
    multi-Page form. Omitted keeps the legacy single-Page behavior; with more
    than one active Page the legacy form is ambiguous and refuses with 409 so
    the caller must pick a Page explicitly. Assignment rows are kept either
    way (decision D6): reconnecting restores the catalog as configured.
    """
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        unsubscribe_app_from_page,
    )

    resolver = FacebookAccountResolver(db)
    if page_id:
        target_key = page_id
    else:
        active_refs = [ref for ref in await resolver.list_facebook_accounts() if ref.is_active]
        if not active_refs:
            raise HTTPException(status_code=404, detail="Không tìm thấy Trang Facebook.")
        if len(active_refs) > 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Nhiều Trang đang hoạt động — hãy chọn Trang cụ thể "
                    "để ngắt kết nối."
                ),
            )
        target_key = active_refs[0].account_key

    # Best-effort remote unsubscribe happens immediately before local
    # deactivation. Meta availability must never keep the local channel active.
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_facebook(target_key)
    if cfg is not None:
        try:
            await unsubscribe_app_from_page(target_key, cfg.page_access_token)
        except (FacebookOAuthError, httpx.HTTPError, ValueError) as exc:
            # Best-effort: local disconnect must proceed either way. Logged so
            # a leftover Meta-side subscription is at least visible, not silent.
            logger.info(
                "facebook page unsubscribe failed on disconnect: page_id=%s error=%s: %s",
                target_key,
                type(exc).__name__,
                exc,
            )

    lifecycle = FacebookPageLifecycle(db)
    account = await lifecycle.disconnect(page_id=target_key, admin_id=admin.id)
    if account is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy Trang Facebook.")
    return FacebookAccountStatusOut(
        page_id=target_key,
        page_id_suffix=target_key[-4:],
        label=account.label,
        status=account.status,
    )


# ─── Facebook Page↔Project assignment CRUD (multi-Page) ─────────────────────
#
# Admin-only editor surface over the ``channel_account_projects`` join table.
# Business logic lives in FacebookPageAssignments (channels provider service);
# this section is transport only. The 409 zero-ACTIVE-project gate applies
# ONLY at activation (POST /facebook/oauth/complete): an INACTIVE Page may
# legitimately hold zero active-project mappings, and removing the last
# assignment of an ACTIVE Page is allowed (its runtime catalog empties until
# an assignment returns — the same defense-in-depth empty-catalog behavior as
# an unmapped Page). Disconnect keeps assignment rows; removal happens only
# through the service surface.


def _assignments_out(page_id: str, views) -> FacebookPageProjectsOut:
    """Map service-layer assignment views onto the response schema."""
    return FacebookPageProjectsOut(
        page_id=page_id,
        assignments=[
            FacebookPageProjectAssignmentOut(
                project_id=view.project_id,
                project_slug=view.project_slug,
                project_name=view.project_name,
                project_active=view.project_active,
            )
            for view in views
        ],
    )


@router.get("/facebook/pages/{page_id}/projects", response_model=FacebookPageProjectsOut)
async def get_facebook_page_projects(
    page_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageProjectsOut:
    """List a Page's assigned Projects (any account lifecycle status)."""
    from app.channels.providers.facebook_account import (
        FacebookPageAssignments,
        FacebookPageNotFoundError,
    )

    service = FacebookPageAssignments(db)
    try:
        account = await service.load_page(page_id)
    except FacebookPageNotFoundError:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy Trang Facebook."
        ) from None
    return _assignments_out(
        account.account_key, await service.assignments(account.id)
    )


@router.put("/facebook/pages/{page_id}/projects", response_model=FacebookPageProjectsOut)
async def replace_facebook_page_projects(
    body: FacebookPageProjectsUpdate,
    page_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageProjectsOut:
    """Replace-all save from the multi-select editor (service-side atomic)."""
    from app.channels.providers.facebook_account import (
        FacebookPageAssignments,
        FacebookPageAssignmentInvalidError,
        FacebookPageNotFoundError,
    )

    service = FacebookPageAssignments(db)
    try:
        account, views = await service.replace(
            page_id=page_id, project_ids=body.project_ids, actor_id=admin.id
        )
    except FacebookPageNotFoundError:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy Trang Facebook."
        ) from None
    except FacebookPageAssignmentInvalidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _assignments_out(account.account_key, views)


@router.post("/facebook/pages/{page_id}/projects", response_model=FacebookPageProjectsOut)
async def add_facebook_page_project(
    body: FacebookPageProjectAdd,
    page_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageProjectsOut:
    """Add one Project assignment. Idempotent when already assigned."""
    from app.channels.providers.facebook_account import (
        FacebookPageAssignments,
        FacebookPageAssignmentInvalidError,
        FacebookPageNotFoundError,
    )

    service = FacebookPageAssignments(db)
    try:
        account, views, _added = await service.add(
            page_id=page_id, project_id=body.project_id, actor_id=admin.id
        )
    except FacebookPageNotFoundError:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy Trang Facebook."
        ) from None
    except FacebookPageAssignmentInvalidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _assignments_out(account.account_key, views)


@router.delete(
    "/facebook/pages/{page_id}/projects/{project_id}",
    response_model=FacebookPageProjectsOut,
)
async def remove_facebook_page_project(
    page_id: str,
    project_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageProjectsOut:
    """Remove one Project assignment (404 when that assignment does not exist)."""
    from app.channels.providers.facebook_account import (
        FacebookPageAssignments,
        FacebookPageNotFoundError,
    )

    service = FacebookPageAssignments(db)
    try:
        views = await service.remove(
            page_id=page_id, project_id=project_id, actor_id=admin.id
        )
    except FacebookPageNotFoundError:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy Trang Facebook."
        ) from None
    if views is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy dự án được gán cho Trang này.",
        )
    return _assignments_out(page_id, views)
