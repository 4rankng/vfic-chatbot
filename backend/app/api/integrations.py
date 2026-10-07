"""Admin integration settings routes.

Transport only: each handler parses the request, calls the owning service
(``services/integrations`` for the channel diagnostics and OAuth flows,
``services/integration_settings`` for credential persistence), maps the domain
error, and returns the response model.
"""

import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.identity.application.http import AuthenticatedUser as User
from app.schemas.integrations import (
    FacebookAccountStatusOut,
    FacebookChannelTestOut,
    FacebookCredentialsOut,
    GeocoderIntegrationSettingsOut,
    GeocoderIntegrationSettingsUpdate,
    FacebookCredentialsReveal,
    FacebookCredentialsUpdate,
    FacebookIntegrationOut,
    FacebookOAuthCompleteRequest,
    FacebookOAuthStartOut,
    FacebookPageListOut,
    FacebookPageProjectAdd,
    FacebookPageProjectAssignmentOut,
    FacebookPageProjectsOut,
    FacebookPageProjectsUpdate,
    CustomLlmIntegrationSettingsOut,
    CustomLlmIntegrationSettingsUpdate,
    CustomLlmIntegrationTestOut,
    EmailDigestSettingsOut,
    EmailDigestSettingsUpdate,
    EmailDigestTestIn,
    EmailDigestTestOut,
    JevIntegrationSettingsOut,
    JevIntegrationSettingsUpdate,
    JevIntegrationTestOut,
    CustomLlmProbeIn,
    MinimaxIntegrationSettingsOut,
    MinimaxIntegrationSettingsUpdate,
    MinimaxIntegrationTestOut,
    OpenRouterIntegrationSettingsOut,
    OpenRouterIntegrationSettingsUpdate,
    OpenRouterIntegrationTestOut,
    TingtingIntegrationSettingsOut,
    TingtingIntegrationSettingsUpdate,
    ZaloChannelTestOut,
    ZaloIntegrationSettingsOut,
    ZaloIntegrationSettingsUpdate,
    ZaloOaSignatureVerifyOut,
    ZaloOaSignatureVerifyRequest,
)
from app.composition.email_digest import build_digest_summarizer_for
from app.services.email_digest import send_test_digest
from app.services.integration_settings import IntegrationSettingsService
from app.services.integrations.facebook_oauth_flow import (
    FacebookOAuthCallbackOutcome,
    complete_page_selection,
    disconnect_page,
    facebook_callback_origin,
    list_oauth_pages,
    probe_facebook_connection,
    run_oauth_callback,
    start_oauth_flow,
)
from app.services.integrations.llm_diagnostics import (
    probe_custom_llm,
    probe_jev,
    probe_minimax,
    probe_openrouter,
)
from app.services.integrations.zalo_diagnostics import (
    probe_zalo_bot_channel,
    probe_zalo_oa_channel,
    sync_bot_webhook,
)
from app.services.zalo_oa_signature import verify_signature
from app.shared.domain.errors import NotFoundError, ValidationError
from app.shared.infrastructure.db import get_request_db as get_db

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])

logger = logging.getLogger(__name__)


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
    view["zalo_bot_webhook_sync"] = await sync_bot_webhook(settings_service, changed)
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
    return await probe_zalo_bot_channel(db)


@router.post("/zalo/oa/test", response_model=ZaloChannelTestOut)
async def test_zalo_oa(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloChannelTestOut:
    """Full diagnostic of the Zalo OA channel — checks 3 layers:

    1. All credentials configured (app_id, secret_key, access_token, refresh_token)
    2. Access token valid (getoa probe)
    3. Token refresh works (delegated to the provider, which persists whatever
       it is issued — a refresh token is single-use, so the probe never
       redeems one just to diagnose it)

    Returns granular diagnostics so the admin knows exactly which credential
    is broken, instead of a generic "not connected" with no actionable info.
    """
    return await probe_zalo_oa_channel(db)


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


@router.get("/geocoder", response_model=GeocoderIntegrationSettingsOut)
async def get_geocoder_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GeocoderIntegrationSettingsOut:
    return GeocoderIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_geocoder_view()
    )


@router.put("/geocoder", response_model=GeocoderIntegrationSettingsOut)
async def update_geocoder_integration_settings(
    body: GeocoderIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GeocoderIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_geocoder(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return GeocoderIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_geocoder_view()
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
    return await probe_minimax(db)


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
    return await probe_openrouter(db)


@router.get("/custom-llm", response_model=CustomLlmIntegrationSettingsOut)
async def get_custom_llm_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CustomLlmIntegrationSettingsOut:
    return CustomLlmIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_custom_llm_view()
    )


@router.put("/custom-llm", response_model=CustomLlmIntegrationSettingsOut)
async def update_custom_llm_integration_settings(
    body: CustomLlmIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CustomLlmIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_custom_llm(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return CustomLlmIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_custom_llm_view()
    )


@router.get("/jev", response_model=JevIntegrationSettingsOut)
async def get_jev_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JevIntegrationSettingsOut:
    return JevIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_jev_view()
    )


@router.put("/jev", response_model=JevIntegrationSettingsOut)
async def update_jev_integration_settings(
    body: JevIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JevIntegrationSettingsOut:
    await IntegrationSettingsService(db).update_jev(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return JevIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_jev_view()
    )


@router.post("/jev/test", response_model=JevIntegrationTestOut)
async def test_jev_integration_settings(
    body: JevIntegrationSettingsUpdate | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> JevIntegrationTestOut:
    """Make a real systemone call so a bad key fails here, not in a live turn.

    Credentials may be supplied in the body so they can be validated BEFORE
    being saved; anything omitted falls back to the stored configuration.
    """
    return await probe_jev(body, db)


@router.get("/email-digest", response_model=EmailDigestSettingsOut)
async def get_email_digest_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailDigestSettingsOut:
    return EmailDigestSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_email_digest_view()
    )


@router.put("/email-digest", response_model=EmailDigestSettingsOut)
async def update_email_digest_settings(
    body: EmailDigestSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailDigestSettingsOut:
    view = await IntegrationSettingsService(db).update_email_digest(
        body.model_dump(exclude_unset=True),
        actor_id=admin.id,
    )
    return EmailDigestSettingsOut.model_validate(view)


@router.post("/email-digest/test", response_model=EmailDigestTestOut)
async def test_email_digest(
    body: EmailDigestTestIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailDigestTestOut:
    """Preview send: the real pending digest to the typed address (no state
    write), exactly what a scheduled run would deliver to recipients."""
    try:
        summarizer = await build_digest_summarizer_for(db)
    except Exception:  # noqa: BLE001 — a preview must still render without summaries
        logger.warning(
            "email digest preview: summarizer unavailable, sending without",
            exc_info=True,
        )
        summarizer = None
    return await send_test_digest(
        db, to_email=str(body.to_email), summarizer=summarizer
    )


@router.get("/tingting", response_model=TingtingIntegrationSettingsOut)
async def get_tingting_integration_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TingtingIntegrationSettingsOut:
    """The deployment-wide TingTing app API key (status only, never the value)."""
    return TingtingIntegrationSettingsOut.model_validate(
        await IntegrationSettingsService(db).admin_tingting_view()
    )


@router.put("/tingting", response_model=TingtingIntegrationSettingsOut)
async def update_tingting_integration_settings(
    body: TingtingIntegrationSettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TingtingIntegrationSettingsOut:
    """Save the TingTing API key and hotline.

    The support OA's Zalo credentials are not admin input any more: payroll
    solely owns and rotates that token pair (push to
    /webhooks/zalo-oa-token + pull from its GET endpoint).
    """
    service = IntegrationSettingsService(db)
    await service.update_tingting(body.model_dump(exclude_unset=True), actor_id=admin.id)
    return TingtingIntegrationSettingsOut.model_validate(
        await service.admin_tingting_view()
    )


@router.post("/custom-llm/test", response_model=CustomLlmIntegrationTestOut)
async def test_custom_llm_integration_settings(
    body: CustomLlmProbeIn | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CustomLlmIntegrationTestOut:
    """Make a real chat call against the failover provider.

    Unlike the minimax/openrouter probes, which only assert a key is present,
    this sends an actual minimal completion. A provider that is unreachable,
    rejects the credential, or does not know the model id must fail here rather
    than during a live candidate conversation.

    Credentials may be supplied in the body so they can be validated BEFORE
    being saved; anything omitted falls back to the stored configuration.
    """
    return await probe_custom_llm(body, db)


# ─── Facebook / Messenger OAuth lifecycle (Phase 4) ─────────────────────────
#
# Every endpoint except the provider callback is admin-only. The callback is
# authenticated by its one-time state because Meta's browser redirect cannot
# carry the app's Bearer header. Responses carry no tokens, app secrets, or raw
# PSIDs. OAuth state/flow records are Redis-backed, single-use, short-TTL, and
# bound to the initiating admin's id + JWT version. Transient Page-credential
# capsules are encrypted at rest in Redis (never plaintext). Flow orchestration
# lives in ``services/integrations/facebook_oauth_flow.py``; this section maps
# outcomes onto redirects and response models.
#
# The five-step flow:
#   1. start      → returns the official authorization URL
#   2. callback   → validates state, exchanges code server-side, stores flow
#   3. pages      → returns safe Page summaries for selection
#   4. complete   → selects one Page, probes identity, subscribes, persists
#   5. test/disconnect/GET → status, health probe, disconnect


def _fb_frontend_redirect_url(
    *, status: str, flow_id: str | None = None, error: str | None = None
) -> str:
    """Build the fixed Settings redirect without provider-controlled values."""
    query: dict[str, str] = {"facebook_oauth_status": status}
    if flow_id:
        query["facebook_oauth_flow_id"] = flow_id
    if error:
        query["facebook_oauth_error"] = error
    return f"{facebook_callback_origin()}/#/settings?{urlencode(query)}"


_FB_REDIRECT_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def _fb_oauth_redirect(outcome: FacebookOAuthCallbackOutcome) -> RedirectResponse:
    return RedirectResponse(
        _fb_frontend_redirect_url(
            status=outcome.status, flow_id=outcome.flow_id, error=outcome.error
        ),
        status_code=302,
        headers=_FB_REDIRECT_HEADERS,
    )


@router.post("/facebook/oauth/start", response_model=FacebookOAuthStartOut)
async def start_facebook_oauth(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookOAuthStartOut:
    """Begin Facebook Login for Business. Stores single-use state in Redis."""
    return await start_oauth_flow(db, admin)


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
    return _fb_oauth_redirect(await run_oauth_callback(state=state, code=code, db=db))


@router.get("/facebook/oauth/pages", response_model=FacebookPageListOut)
async def list_facebook_pages(
    flow_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookPageListOut:
    """Return the safe Page list stored in the flow record."""
    return await list_oauth_pages(flow_id=flow_id, admin=admin, db=db)


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
    return await complete_page_selection(payload, admin, db)


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
    return await probe_facebook_connection(db)


@router.get("/facebook/credentials", response_model=FacebookCredentialsOut)
async def get_facebook_credentials(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookCredentialsOut:
    """Safe status of the app-level Meta credentials (configured flag + status, no secret characters)."""
    return FacebookCredentialsOut.model_validate(
        await IntegrationSettingsService(db).admin_facebook_oauth_view()
    )


@router.post("/facebook/credentials/reveal", response_model=FacebookCredentialsReveal)
async def reveal_facebook_credentials(
    response: Response,
    password: str = Body(..., embed=True, min_length=1, max_length=256),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FacebookCredentialsReveal:
    """Return the stored Meta secrets in plaintext to a re-authenticated admin.

    Re-registering the webhook on Meta needs the verify token verbatim. POST
    rather than GET so the response is never cached, prefetched, or replayed
    from browser history; ``no-store`` closes the same gap at the proxy.

    SEC-07: the body must carry the admin's password again (step-up), so a
    hijacked admin session on its own cannot read the Meta app secret — the HMAC
    key that authenticates every inbound Messenger webhook. The reveal is
    audit-logged by actor; the values themselves are never logged.
    """
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.reveal_facebook_oauth(
        actor_id=admin.id,
        password=password,
        password_hash=admin.password_hash,
    )
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
    return await disconnect_page(page_id, admin, db)


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
        raise NotFoundError("Không tìm thấy Trang Facebook.") from None
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
        raise NotFoundError("Không tìm thấy Trang Facebook.") from None
    except FacebookPageAssignmentInvalidError as exc:
        raise ValidationError(str(exc)) from None
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
        raise NotFoundError("Không tìm thấy Trang Facebook.") from None
    except FacebookPageAssignmentInvalidError as exc:
        raise ValidationError(str(exc)) from None
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
        raise NotFoundError("Không tìm thấy Trang Facebook.") from None
    if views is None:
        raise NotFoundError("Không tìm thấy dự án được gán cho Trang này.")
    return _assignments_out(page_id, views)
