"""Admin integration settings routes."""
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.redis import get_redis
from app.models.user import User
from app.schemas.integrations import (
    MinimaxIntegrationSettingsOut,
    MinimaxIntegrationSettingsUpdate,
    MinimaxIntegrationTestOut,
    OpenRouterIntegrationSettingsOut,
    OpenRouterIntegrationSettingsUpdate,
    OpenRouterIntegrationTestOut,
    ZaloIntegrationSettingsOut,
    ZaloIntegrationSettingsUpdate,
    ZaloIntegrationTestOut,
    ZaloOAuthDisconnectOut,
    ZaloOAuthStartOut,
)
from app.services.integration_settings import IntegrationSettingsService
from app.services.zalo_oa_oauth import ZaloOAOAuthClient, ZaloOAOAuthError

router = APIRouter(prefix="/admin/integrations", tags=["integrations"])

# Single-use OAuth state TTL (Zalo auth codes are themselves valid 10 min).
_OAUTH_STATE_TTL_SECONDS = 600
_OAUTH_STATE_KEY = "zalo:oauth:state:{state}"
# Refresh slightly before the token's stated expiry so the stored value already
# accounts for clock skew + in-flight latency.
_OA_TOKEN_SAFETY_MARGIN_SECONDS = 300


def _oauth_redirect_uri(settings: Settings, request: Request) -> str:
    """Public HTTPS callback URL for the OAuth flow.

    Explicit setting wins; otherwise derive from the proxy headers (Caddy sets
    X-Forwarded-Proto / X-Forwarded-Host) so the value matches what the browser
    actually hit.
    """
    if settings.zalo_oa_oauth_redirect_url:
        return settings.zalo_oa_oauth_redirect_url.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{scheme}://{host}/api/v1/admin/integrations/zalo/oauth/callback"


def _postmessage_target(settings: Settings, request: Request) -> str:
    """Origin allowed to receive the OAuth result postMessage.

    The popup is opened by the CRM tab; that tab's origin is the only valid
    target. Prefer the opener's own ``Origin`` header (sent on the /start fetch),
    validated against CORS_ORIGINS so an attacker can't retarget the message by
    spoofing the header. Fall back to the first configured origin. Never '*'.
    """
    allowed = settings.cors_origins_list
    opener = request.headers.get("origin")
    if opener and opener in allowed:
        return opener
    return allowed[0] if allowed else ""


def _callback_html(target_origin: str, *, payload: dict) -> HTMLResponse:
    """Tiny page that hands the result to the opening CRM window, then closes.

    The popup is opened by the CRM; Zalo redirects it here with code/state. We
    postMessage the outcome to the opener (restricted to the CRM origin) and
    close the popup. Tokens never reach the browser — only success/error + the
    OA display name.
    """
    # JSON literals are safe to splice into a <script> as JS values. The one
    # remaining vector is a ``</script>`` substring inside a string field
    # (e.g. an upstream error message) breaking out of the tag — neutralize it.
    data_json = json.dumps(payload).replace("</", "<\\/")
    origin_json = json.dumps(target_origin)
    script = (
        "var data = " + data_json + ";\n"
        "var origin = " + origin_json + ";\n"
        "try { window.opener.postMessage(data, origin); } catch (e) {}\n"
        "setTimeout(function(){ window.close(); }, 150);"
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Kết nối Zalo OA</title></head><body>"
        "<script>\n(function(){\n" + script + "\n})();\n</script></body></html>"
    )
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


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


@router.post("/zalo/oauth/start", response_model=ZaloOAuthStartOut)
async def start_zalo_oa_oauth(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloOAuthStartOut:
    """Begin scan-to-connect: mint a single-use CSRF state, return Zalo's URL.

    The frontend opens ``authorize_url`` in a popup; Zalo renders the QR there.
    """
    cfg = await IntegrationSettingsService(db).resolve_zalo()
    if not cfg.oa_app_id:
        raise HTTPException(
            status_code=400,
            detail="Cần cấu hình OA App ID trước khi kết nối qua QR.",
        )
    settings = get_settings()
    redirect_uri = _oauth_redirect_uri(settings, request)
    # The popup's result is postMessage'd to the CRM tab that opened it. Capture
    # THAT origin now (validated against CORS) so the public callback can target
    # it exactly instead of guessing from config ordering.
    target_origin = _postmessage_target(settings, request)
    state = secrets.token_urlsafe(32)
    await redis_set_state(state, admin.id, redirect_uri, target_origin)
    authorize_url = ZaloOAOAuthClient(cfg.oa_app_id, cfg.oa_secret_key).build_authorize_url(
        redirect_uri, state
    )
    return ZaloOAuthStartOut(authorize_url=authorize_url)


@router.get("/zalo/oauth/callback")
async def zalo_oa_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Public OAuth callback. The Zalo redirect carries no JWT, so the single-use
    state minted in /start is the sole guard — consume it atomically first.

    On success the OA token trio is persisted (encrypted) and a tiny HTML page
    postMessages the result to the opening CRM window, then closes the popup.
    """
    settings = get_settings()
    # Best-available target before the state is consumed (used only for the
    # pre-state error paths). Once the state is read, the opener origin pinned in
    # /start takes over — never '*' and never guessed from public headers.
    default_origin = settings.cors_origins_list[0] if settings.cors_origins_list else ""

    def fail(message: str, origin: str = default_origin) -> HTMLResponse:
        return _callback_html(
            origin, payload={"type": "zalo_oauth_error", "message": message}
        )

    if error:
        return fail(error_description or error or "người dùng từ chối")
    if not code or not state:
        return fail("Thiếu code/state từ Zalo.")

    raw = await get_redis().getdel(_OAUTH_STATE_KEY.format(state=state))
    if not raw:
        return fail("Phiên kết nối đã hết hạn hoặc không hợp lệ — vui lòng thử lại.")
    try:
        session_payload = json.loads(raw)
    except (TypeError, ValueError):
        return fail("Phiên kết nối bị hỏng.")
    # Both values were pinned in /start; trust them, never the public callback
    # request headers (which an attacker could influence via proxy forwarding).
    redirect_uri = session_payload.get("redirect_uri")
    target_origin = session_payload.get("target_origin") or default_origin
    admin_id_raw = session_payload.get("admin_id")
    if not redirect_uri:
        return fail("Phiên kết nối bị hỏng (thiếu redirect_uri).", target_origin)

    svc = IntegrationSettingsService(db)
    cfg = await svc.resolve_zalo()
    if not cfg.oa_app_id or not cfg.oa_secret_key:
        return fail("OA App ID / secret chưa cấu hình — không thể đổi token.", target_origin)
    try:
        token_set = await ZaloOAOAuthClient(cfg.oa_app_id, cfg.oa_secret_key).exchange_code(
            code, redirect_uri
        )
    except ZaloOAOAuthError as exc:
        return fail(f"Đổi token thất bại: {exc}", target_origin)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=max(token_set.expires_in - _OA_TOKEN_SAFETY_MARGIN_SECONDS, 60)
    )
    iso = expires_at.isoformat()
    try:
        actor_id = uuid.UUID(admin_id_raw) if admin_id_raw else None
    except ValueError:
        actor_id = None
    await svc.store_oa_tokens(
        access_token=token_set.access_token,
        refresh_token=token_set.refresh_token,
        expires_at=iso,
        actor_id=actor_id,
    )
    oa_name = await fetch_oa_display_name(token_set.access_token)
    return _callback_html(
        target_origin,
        payload={"type": "zalo_oauth_success", "oa_name": oa_name},
    )


@router.delete("/zalo/oauth", response_model=ZaloOAuthDisconnectOut)
async def disconnect_zalo_oa(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ZaloOAuthDisconnectOut:
    """Disconnect: clear the OAuth-managed OA tokens (keeps app_id/secret)."""
    await IntegrationSettingsService(db).clear_zalo_oa_tokens(actor_id=admin.id)
    return ZaloOAuthDisconnectOut(disconnected=True)


async def redis_set_state(
    state: str, admin_id: uuid.UUID, redirect_uri: str, target_origin: str
) -> None:
    """Store a single-use, time-boxed OAuth state in Redis.

    Carries the opener origin + redirect_uri so the public callback never has to
    trust its own request headers for either.
    """
    payload = json.dumps(
        {
            "admin_id": str(admin_id),
            "redirect_uri": redirect_uri,
            "target_origin": target_origin,
            "created_at": time.time(),
        }
    )
    await get_redis().set(
        _OAUTH_STATE_KEY.format(state=state), payload, ex=_OAUTH_STATE_TTL_SECONDS
    )


async def fetch_oa_display_name(access_token: str) -> str:
    """Best-effort OA name for the success toast. Any failure -> empty string.

    Purely cosmetic; the connect has already succeeded by the time this runs.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://openapi.zalo.me/v2.0/oa/getoa",
                headers={"access_token": access_token},
            )
        data = resp.json()
    except Exception:  # noqa: BLE001 — best-effort, never fatal
        return ""
    inner = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(inner, dict):
        return ""
    for key in ("oa_name", "name"):
        value = inner.get(key)
        if value:
            # Cap so a pathological upstream payload can't push a huge toast.
            return str(value)[:200]
    return ""


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
