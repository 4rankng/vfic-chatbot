"""Facebook Login for Business + Graph API client (Phase 4).

Provider-owned HTTP client for the OAuth exchange, Page discovery, identity
probe, and webhook subscription. Uses the shared httpx client. Never logs raw
response bodies (they can contain tokens). The Meta Graph API version is pinned
centrally in config (``meta_graph_api_version``).

Required permissions (revalidated 2026-07-17 against the official docs):
``pages_show_list``, ``pages_manage_metadata``, ``pages_messaging``,
``public_profile`` (advanced access for go-live).

This module is imported only by the OAuth/account-lifecycle layer
(``facebook_account.py``) and the admin endpoints. The shared ingress, graph,
and dispatch services must NOT import it — they resolve through the
:class:`ChannelAccountResolver` port.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from app.core.config import get_settings
from app.core.http import get_http_client

if TYPE_CHECKING:
    from app.services.integration_settings import FacebookRuntimeConfig

logger = logging.getLogger(__name__)

_FACEBOOK_OAUTH_DIALOG_ORIGIN = "https://www.facebook.com"

# Required permissions for Messenger Platform (revalidated 2026-07-17).
MESSENGER_PERMISSIONS = (
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "public_profile",
)


@dataclass(frozen=True)
class FacebookPageSummary:
    """Safe Page summary returned to the admin during OAuth Page selection.

    Only the Page id + name cross this boundary; access tokens never do.
    """

    id: str
    name: str
    # `tasks` carries the Page-role permissions (e.g. MANAGE, MESSENGER) so the
    # complete step can verify the admin can actually message on this Page.
    tasks: tuple[str, ...] = ()


class FacebookOAuthError(RuntimeError):
    """A definite failure in the OAuth exchange or Graph API call.

    Distinct from transport ambiguity — this is a provider-reported rejection
    or a malformed envelope, not a timeout-then-accept risk. Carries the Meta
    error ``code`` when the Graph API returned a structured error envelope so
    callers can classify (e.g. code 190 = auth-related → auth_revoked) without
    brittle substring matching on the message text.
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _error_code_from_envelope(data: dict) -> int | None:
    """Extract the Meta error code from a Graph API error envelope.

    Meta returns ``{"error": {"code": <int>, "error_subcode": <int>, "message": ...}}``.
    Code 190 = invalid/expired/revoked access token (the auth-revoked signal).
    """
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _graph_base() -> str:
    s = get_settings()
    return f"{s.meta_graph_api_base.rstrip('/')}/{s.meta_graph_api_version}"


async def _bounded_post(url: str, *, params: dict | None = None, json_body: dict | None = None) -> dict:
    """POST with bounded response + redaction. Never logs the body."""
    s = get_settings()
    client = await get_http_client("facebook_oauth", timeout=30, settings=s)
    resp = await client.post(url, params=params, json=json_body)
    data = resp.json()
    if not isinstance(data, dict):
        raise FacebookOAuthError(f"non-JSON Graph response (status {resp.status_code})")
    return data


async def _bounded_get(url: str, *, params: dict | None = None) -> dict:
    s = get_settings()
    client = await get_http_client("facebook_oauth", timeout=30, settings=s)
    resp = await client.get(url, params=params)
    data = resp.json()
    if not isinstance(data, dict):
        raise FacebookOAuthError(f"non-JSON Graph response (status {resp.status_code})")
    return data


def build_authorization_url(*, state: str, redirect_uri: str) -> str:
    """Compose the official Facebook Login for Business authorization URL.

    ``state`` is the opaque, single-use, admin-bound Redis record. The config
    ID selects the Login for Business flow (``meta_login_config_id``).
    """
    s = get_settings()
    query = urlencode(
        {
            "client_id": s.meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(MESSENGER_PERMISSIONS),
            "config_id": s.meta_login_config_id,
        }
    )
    return (
        f"{_FACEBOOK_OAUTH_DIALOG_ORIGIN}/{s.meta_graph_api_version}/dialog/oauth?{query}"
    )


async def exchange_code_for_user_token(*, code: str, redirect_uri: str) -> str:
    """Exchange the OAuth code for a short-lived user access token.

    Server-side only; the code never reaches the browser. Raises
    :class:`FacebookOAuthError` on any definite failure.
    """
    s = get_settings()
    data = await _bounded_post(
        f"{_graph_base()}/oauth/access_token",
        params={
            "client_id": s.meta_app_id,
            "client_secret": s.meta_app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    token = data.get("access_token")
    if not token:
        error = data.get("error") or {}
        raise FacebookOAuthError(
            f"oauth exchange failed: {error.get('message') or data}"
        )
    return str(token)


async def list_pages(user_access_token: str) -> list[FacebookPageSummary]:
    """Return the Pages the user manages, with safe summaries only."""
    data = await _bounded_get(
        f"{_graph_base()}/me/accounts",
        params={"access_token": user_access_token, "fields": "id,name,tasks"},
    )
    pages = data.get("data") or []
    summaries: list[FacebookPageSummary] = []
    for raw in pages:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        tasks = raw.get("tasks") or []
        summaries.append(
            FacebookPageSummary(
                id=str(raw["id"]),
                name=str(raw.get("name") or raw["id"]),
                tasks=tuple(str(t) for t in tasks) if isinstance(tasks, list) else (),
            )
        )
    return summaries


async def get_page_access_token(user_access_token: str, page_id: str) -> str:
    """Resolve the long-lived Page access token for one Page.

    The user token must have ``pages_show_list`` + ``pages_messaging``. The
    returned Page token is long-lived and is what we persist (encrypted).
    """
    pages = await list_pages(user_access_token)
    for page in pages:
        if page.id == page_id:
            data = await _bounded_get(
                f"{_graph_base()}/{page_id}",
                params={
                    "access_token": user_access_token,
                    "fields": "access_token",
                },
            )
            token = data.get("access_token")
            if token:
                return str(token)
    raise FacebookOAuthError(f"page {page_id} not found or no messaging permission")


async def probe_page_identity(page_access_token: str) -> str:
    """Verify the Page token by fetching the Page id; return it.

    Used at OAuth completion to prove the token works before persisting +
    subscribing. Raises :class:`FacebookOAuthError` on a revoked/invalid token.
    """
    data = await _bounded_get(
        f"{_graph_base()}/me", params={"access_token": page_access_token}
    )
    page_id = data.get("id")
    if not page_id:
        raise FacebookOAuthError(f"page identity probe failed: {data.get('error') or data}")
    return str(page_id)


async def subscribe_app_to_page(page_id: str, page_access_token: str) -> None:
    """Subscribe the Meta App to the Page for Messenger webhook fields.

    Idempotent: re-subscribing a Page that is already subscribed is a no-op.
    Raises :class:`FacebookOAuthError` on a definite failure.
    """
    data = await _bounded_post(
        f"{_graph_base()}/{page_id}/subscribed_apps",
        params={"access_token": page_access_token},
        json_body={"subscribed_fields": "messages,messaging_postbacks"},
    )
    if data.get("success") is not True:
        # Meta's contract is an explicit boolean acknowledgement. Empty,
        # false, string, numeric, and error envelopes all fail closed without
        # copying the provider response (which may contain sensitive context).
        raise FacebookOAuthError("page subscription failed")


async def unsubscribe_app_from_page(page_id: str, page_access_token: str) -> None:
    """Best-effort unsubscribe on disconnect. Failures are logged, not fatal."""
    s = get_settings()
    try:
        client = await get_http_client("facebook_oauth", timeout=15, settings=s)
        await client.delete(
            f"{_graph_base()}/{page_id}/subscribed_apps",
            params={"access_token": page_access_token},
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.info("facebook unsubscribe best-effort failed for page=%s", page_id)


async def send_message(
    config: "FacebookRuntimeConfig", *, recipient_psid: str, text: str
) -> dict:
    """Send one text via the Send API. Returns the bounded Graph response.

    Called by the Messenger adapter (Phase 5). Kept here so all Graph API
    transport lives in one provider module. Raises :class:`FacebookOAuthError`
    on a definite provider rejection.
    """
    data = await _bounded_post(
        f"{config.graph_api_base.rstrip('/')}/{config.graph_api_version}/me/messages",
        params={"access_token": config.page_access_token},
        json_body={
            "recipient": {"id": recipient_psid},
            "message": {"text": text},
        },
    )
    if data.get("error"):
        raise FacebookOAuthError(
            "messenger send rejected",
            code=_error_code_from_envelope(data),
        )
    return data


__all__ = [
    "FacebookPageSummary",
    "FacebookOAuthError",
    "MESSENGER_PERMISSIONS",
    "build_authorization_url",
    "exchange_code_for_user_token",
    "list_pages",
    "get_page_access_token",
    "probe_page_identity",
    "subscribe_app_to_page",
    "unsubscribe_app_from_page",
    "send_message",
]
