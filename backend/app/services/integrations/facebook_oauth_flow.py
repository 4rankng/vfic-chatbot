"""Facebook OAuth flow orchestration: Redis state, code exchange, Page wiring.

Owns the five-step admin flow that used to live in the integrations router:
state issuance, the server-side code exchange, the Page-selection flow store,
subscribe/unsubscribe against the Graph API, and disconnect. Responses carry
no tokens or app secrets; transient Page-credential capsules are encrypted at
rest in Redis (never plaintext). The router only maps
:class:`FacebookOAuthCallbackOutcome` onto the browser redirect.

The five-step flow:
  1. start      → returns the official authorization URL
  2. callback   → validates state, exchanges code server-side, stores flow
  3. pages      → returns safe Page summaries for selection
  4. complete   → selects one Page, probes identity, subscribes, persists
  5. test/disconnect/GET → status, health probe, disconnect
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.application.http import AuthenticatedUser as User
from app.integrations.admin_runtime import (
    get_integration_redis,
    get_integration_settings,
    load_enabled_admin,
)
from app.schemas.integrations import (
    FacebookAccountStatusOut,
    FacebookChannelTestOut,
    FacebookOAuthCompleteRequest,
    FacebookOAuthStartOut,
    FacebookPageListOut,
    FacebookPageOut,
)
from app.services.integration_settings import IntegrationSettingsService
from app.shared.domain.errors import (
    BadRequestError,
    ConflictError,
    GoneError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)

logger = logging.getLogger(__name__)

_FB_OAUTH_STATE_PREFIX = "fb_oauth_state:"
_FB_OAUTH_TTL_SECONDS = 300  # 5 minutes — single-use, short-lived


async def _redis():
    return get_integration_redis()


def facebook_callback_origin() -> str:
    """Return the deployment-owned first allowlisted OAuth origin."""
    settings = get_integration_settings()
    return next(iter(settings.facebook_callback_allowlist or ["http://localhost:5173"])).rstrip("/")


def facebook_callback_url() -> str:
    """The server-side OAuth callback URI. Allowlisted in config."""
    return f"{facebook_callback_origin()}/api/v1/admin/integrations/facebook/oauth/callback"


async def facebook_oauth_coordinator():
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


async def load_facebook_oauth_flow(*, flow_id: str, admin: User, consume: bool = False):
    """Load a valid OAuth flow owned by this exact authenticated session."""
    from app.integrations.facebook_oauth import FacebookOAuthFlowUnavailable

    coordinator = await facebook_oauth_coordinator()
    try:
        return await coordinator.load_flow(
            flow_id=flow_id,
            admin_id=admin.id,
            token_version=int(admin.token_version),
            consume=consume,
        )
    except FacebookOAuthFlowUnavailable:
        pass
    raise GoneError("Phiên chọn Trang không hợp lệ hoặc đã hết hạn. Vui lòng kết nối lại.")


async def start_oauth_flow(db: AsyncSession, admin: User) -> FacebookOAuthStartOut:
    """Begin Facebook Login for Business. Stores single-use state in Redis."""
    from app.channels.providers.facebook_oauth import build_authorization_url

    # Resolve app credentials DB-first (env fallback). A missing app_id would
    # otherwise build an OAuth URL with an empty client_id, which Facebook
    # rejects with a generic "Invalid app ID" page. Surface a clear Vietnamese
    # 400 here so the admin knows to configure credentials first.
    settings_service = IntegrationSettingsService(db)
    oauth_cfg = await settings_service.resolve_facebook_oauth()
    if not oauth_cfg.app_id:
        raise BadRequestError(
            "Chưa cấu hình Meta App ID. Vào Cài đặt → Facebook Messenger để "
            "cấu hình thông tin ứng dụng Meta trước khi kết nối."
        )
    coordinator = await facebook_oauth_coordinator()
    state = await coordinator.issue_state(
        admin_id=admin.id,
        token_version=int(admin.token_version),
    )
    return FacebookOAuthStartOut(
        authorization_url=build_authorization_url(
            state=state, redirect_uri=facebook_callback_url(), config=oauth_cfg
        )
    )


@dataclass(frozen=True)
class FacebookOAuthCallbackOutcome:
    """Transport-neutral OAuth callback result (the router builds the redirect)."""

    status: str
    flow_id: str | None = None
    error: str | None = None


async def run_oauth_callback(
    state: str, code: str | None, db: AsyncSession
) -> FacebookOAuthCallbackOutcome:
    """Validate state, exchange code server-side, store an encrypted flow record.

    Only ``flow_id`` + ``status`` leave this function; no code, token, or Page
    list crosses to the browser. The flow record stores encrypted Page
    summaries + the user access token (encrypted with the integration cipher,
    never plaintext in Redis).
    """
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        exchange_code_for_user_token,
        list_pages,
    )
    from app.integrations.facebook_oauth import FacebookOAuthInvalidState, FacebookOAuthPage

    coordinator = await facebook_oauth_coordinator()
    try:
        bound_session = await coordinator.consume_state(state=state)
    except FacebookOAuthInvalidState:
        return FacebookOAuthCallbackOutcome(status="error", error="invalid_state")

    admin = await load_enabled_admin(db, bound_session.admin_id)
    if admin is None:
        return FacebookOAuthCallbackOutcome(status="error", error="invalid_admin")
    if admin.token_version != bound_session.token_version:
        return FacebookOAuthCallbackOutcome(status="error", error="session_changed")
    if not code:
        return FacebookOAuthCallbackOutcome(status="error", error="missing_code")

    try:
        # Resolve app credentials DB-first (env fallback) just before the
        # exchange — the callback may have spent seconds in invalid-state /
        # invalid-admin branches above where the config is not yet needed.
        oauth_cfg = await IntegrationSettingsService(db).resolve_facebook_oauth()
        user_token = await exchange_code_for_user_token(
            code=code, redirect_uri=facebook_callback_url(), config=oauth_cfg
        )
        pages = await list_pages(user_token)
    except (FacebookOAuthError, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "facebook oauth code exchange failed: admin=%s error=%s: %s",
            admin.id,
            type(exc).__name__,
            exc,
        )
        return FacebookOAuthCallbackOutcome(status="error", error="exchange_failed")

    if not pages:
        return FacebookOAuthCallbackOutcome(status="error", error="no_pages")

    flow_id = await coordinator.store_flow(
        admin_id=admin.id,
        token_version=int(admin.token_version),
        user_token=user_token,
        pages=[FacebookOAuthPage(id=p.id, name=p.name) for p in pages],
    )
    return FacebookOAuthCallbackOutcome(status="pending_selection", flow_id=flow_id)


async def list_oauth_pages(
    *, flow_id: str, admin: User, db: AsyncSession
) -> FacebookPageListOut:
    """Return the safe Page list stored in the flow record."""
    from app.channels.providers.facebook_account import FacebookAccountResolver

    payload = await load_facebook_oauth_flow(
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


async def complete_page_selection(
    payload: FacebookOAuthCompleteRequest, admin: User, db: AsyncSession
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
            raise ValidationError(str(exc)) from None
        project_ids = [str(pid) for pid in validated]

    flow = await load_facebook_oauth_flow(
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
        # construction, and GET /me would only spend a round trip to re-derive
        # that. subscribe_app_to_page below still fails closed on an unusable
        # token.
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
        raise UpstreamError("Kích hoạt Trang thất bại. Vui lòng kết nối lại.")

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
        raise ConflictError(
            "Trang chưa được gán dự án nào đang hoạt động. "
            "Hãy chọn ít nhất một dự án rồi thử lại."
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


async def probe_facebook_connection(db: AsyncSession) -> FacebookChannelTestOut:
    """Health probe: resolve the active Page, probe its identity, and verify
    the Meta app is subscribed to the Page for webhook events."""
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.channels.providers.facebook_oauth import (
        FacebookOAuthError,
        page_is_app_subscribed,
    )

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
    # A dedicated GET /me identity probe would re-derive the same fact for one
    # more round trip, so it stays out.
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


async def set_bot_pause(
    db: AsyncSession, admin: User, page_id: str, paused: bool
) -> FacebookAccountStatusOut:
    """Set the per-Page bot pause switch (owner request 2026-10-08).

    Paused keeps the Page fully connected — webhooks accepted, every candidate
    message persisted — while the bot stops answering: the inbound scheduler
    does not enqueue a turn, the reconcile sweep skips the Page, and any turn
    already in flight suppresses itself at the run_turn backstop. The action
    is audit-logged by actor like the other Page lifecycle mutations.
    """
    from sqlalchemy import select as sa_select

    from app.channels.accounts import ChannelAccountStatus
    from app.models.channel_account import ChannelAccount

    account = await db.scalar(
        sa_select(ChannelAccount).where(
            ChannelAccount.provider == "facebook_messenger",
            ChannelAccount.account_key == page_id,
            ChannelAccount.status == ChannelAccountStatus.ACTIVE,
        )
    )
    if account is None:
        raise NotFoundError("Không tìm thấy Trang Facebook đang hoạt động.")
    if account.bot_paused != paused:
        account.bot_paused = paused
        await db.commit()
    logger.warning(
        "facebook bot pause set: page_id=%s paused=%s admin=%s",
        page_id,
        paused,
        admin.id,
    )
    return FacebookAccountStatusOut(
        page_id=page_id,
        page_id_suffix=page_id[-4:],
        label=account.label,
        status=account.status,
        bot_paused=account.bot_paused,
    )


async def disconnect_page(
    page_id: str | None, admin: User, db: AsyncSession
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
            raise NotFoundError("Không tìm thấy Trang Facebook.")
        if len(active_refs) > 1:
            raise ConflictError(
                "Nhiều Trang đang hoạt động — hãy chọn Trang cụ thể "
                "để ngắt kết nối."
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
        raise NotFoundError("Không tìm thấy Trang Facebook.")
    return FacebookAccountStatusOut(
        page_id=target_key,
        page_id_suffix=target_key[-4:],
        label=account.label,
        status=account.status,
    )
