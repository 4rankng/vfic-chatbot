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
    from app.services.integration_settings import FacebookOAuthConfig, FacebookRuntimeConfig

logger = logging.getLogger(__name__)

_FACEBOOK_OAUTH_DIALOG_ORIGIN = "https://www.facebook.com"

# Required permissions for Messenger Platform (revalidated 2026-07-17).
#
# ``pages_user_gender`` — the Messenger User Profile API field that backs the
# Vietnamese address form (anh / chị) — is deliberately NOT requested here. It
# needs the Business Asset User Profile Access feature plus App Review, and
# until the app has both, Facebook rejects the WHOLE dialog with
# "Invalid Scope: pages_user_gender", which blocks Page linking entirely.
# Candidate gender is now inferred per turn by Jev (graph/decisions.py), so the
# address form no longer depends on this scope. Re-add it once the app is
# approved for Business Asset User Profile Access.
MESSENGER_PERMISSIONS = (
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "public_profile",
)

# Meta returns this error code for Messenger accounts created from a phone
# number, which have no retrievable profile. It is an expected, permanent
# outcome for that user — not a transport failure worth logging as an error.
_NO_PROFILE_AVAILABLE_ERROR_CODE = 2018218

# Meta's answer when the token cannot read the object at all: code 100 with
# subcode 33, "Object with ID ... does not exist, cannot be loaded due to
# missing permissions, or does not support this operation". For the Messenger
# User Profile API this is what an app without Business Asset User Profile
# Access (and a Page token without ``pages_read_engagement``) gets for EVERY
# PSID — measured on production 2026-09-28 across a full Page's contacts, where
# ``/me`` on the same token reports the missing permission outright. Subcode 33
# is the narrow signal; code 100 alone also covers a malformed request, which
# must keep raising.
_UNREADABLE_OBJECT_ERROR_CODE = 100
_UNREADABLE_OBJECT_ERROR_SUBCODE = 33


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


@dataclass(frozen=True)
class MessengerUserProfile:
    """One person's Messenger profile, as returned by the User Profile API.

    Every field is optional: Meta omits any field the app lacks access to, so a
    profile with only ``first_name`` is a normal result rather than an error.
    ``gender`` is normalised to ``"male"`` / ``"female"`` or left empty — an
    unrecognised provider value is discarded rather than passed through, so it
    can never reach the prompt as an address form.
    """

    first_name: str = ""
    last_name: str = ""
    profile_pic: str = ""
    gender: str = ""

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)


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


def _error_subcode_from_envelope(data: dict) -> int | None:
    """Extract Meta's ``error_subcode``, which narrows what a coarse code means.

    Code 100 is Meta's catch-all for a request it will not serve; only the
    subcode separates "this token cannot read this object" (33) from a genuinely
    malformed request.
    """
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    subcode = error.get("error_subcode")
    try:
        return int(subcode) if subcode is not None else None
    except (TypeError, ValueError):
        return None


def _is_unreadable_object(data: dict) -> bool:
    """Whether Meta refused an object read for this token rather than the request."""
    return (
        _error_code_from_envelope(data) == _UNREADABLE_OBJECT_ERROR_CODE
        and _error_subcode_from_envelope(data) == _UNREADABLE_OBJECT_ERROR_SUBCODE
    )


def _graph_base() -> str:
    """Graph API base + pinned version. Version/base are not secrets and stay
    env-owned (``meta_graph_api_version`` / ``meta_graph_api_base``) per the
    user's scope choice; only the four app credentials move to DB control."""
    s = get_settings()
    return f"{s.meta_graph_api_base.rstrip('/')}/{s.meta_graph_api_version}"


def _graph_base_for(config: "FacebookOAuthConfig") -> str:
    """Variant of :func:`_graph_base` using the resolved config's version/base.

    Used by OAuth-start and the code exchange, which already hold a resolved
    :class:`FacebookOAuthConfig` and so avoid a second ``get_settings()`` read.
    """
    return f"{config.graph_api_base.rstrip('/')}/{config.graph_api_version}"


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


def build_authorization_url(
    *, state: str, redirect_uri: str, config: "FacebookOAuthConfig"
) -> str:
    """Compose the official Facebook Login for Business authorization URL.

    ``state`` is the opaque, single-use, admin-bound Redis record. The config
    ID selects the Login for Business flow (``config.login_config_id``).
    ``config`` is the DB-resolved (env-fallback) app-level credentials; it is
    passed explicitly so this module never reads ``get_settings()`` for
    secrets. Raises :class:`FacebookOAuthError` if ``app_id`` is empty so the
    caller surfaces a clear 400 instead of a Facebook "Invalid app ID" page.
    """
    if not config.app_id:
        raise FacebookOAuthError("missing meta app id")
    query = urlencode(
        {
            "client_id": config.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(MESSENGER_PERMISSIONS),
            "config_id": config.login_config_id,
        }
    )
    return (
        f"{_FACEBOOK_OAUTH_DIALOG_ORIGIN}/{config.graph_api_version}/dialog/oauth?{query}"
    )


async def exchange_code_for_user_token(
    *, code: str, redirect_uri: str, config: "FacebookOAuthConfig"
) -> str:
    """Exchange the OAuth code for a short-lived user access token.

    Server-side only; the code never reaches the browser. Raises
    :class:`FacebookOAuthError` on any definite failure.
    """
    data = await _bounded_post(
        f"{_graph_base_for(config)}/oauth/access_token",
        params={
            "client_id": config.app_id,
            "client_secret": config.app_secret,
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
        # Raise the page size above Graph's default so an admin who manages
        # many Pages still sees every one of them in the selection list.
        params={
            "access_token": user_access_token,
            "fields": "id,name,tasks",
            "limit": "100",
        },
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
    # Read the token straight off the /me/accounts edge. Resolving it via a
    # second GET /{page-id}?fields=access_token call omits the field for Pages
    # whose access is held through Business Manager, which surfaced as a Page
    # the admin could select but never activate.
    data = await _bounded_get(
        f"{_graph_base()}/me/accounts",
        params={
            "access_token": user_access_token,
            "fields": "id,access_token",
            "limit": "100",
        },
    )
    for raw in data.get("data") or []:
        if not isinstance(raw, dict) or str(raw.get("id") or "") != page_id:
            continue
        token = raw.get("access_token")
        if token:
            return str(token)
        raise FacebookOAuthError(
            f"page {page_id} granted no page access token "
            "(missing pages_messaging or Business Manager page access)"
        )
    raise FacebookOAuthError(f"page {page_id} not found in the granted Page list")


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


async def page_is_app_subscribed(
    page_id: str, page_access_token: str, app_id: str
) -> bool:
    """Report whether ``app_id`` receives this Page's webhook events.

    Reads the Page's ``subscribed_apps`` edge with the Page token. Used by the
    health probe to catch a silently-dropped webhook subscription (e.g. after
    another platform changed the Page's integrations) before real traffic
    depends on it. Raises :class:`FacebookOAuthError` on a definite failure or
    when the caller's app id is unknown; returns ``False`` when the Page's
    subscription list resolves without this app.
    """
    if not app_id:
        raise FacebookOAuthError("app id not configured for subscription check")
    data = await _bounded_get(
        f"{_graph_base()}/{page_id}/subscribed_apps",
        # Raise the page size above Graph's default so a Page with many
        # subscribed apps does not paginate our app out of the first page.
        params={"access_token": page_access_token, "limit": "100"},
    )
    if isinstance(data.get("error"), dict):
        # Fail closed without echoing the provider envelope.
        raise FacebookOAuthError("page subscription lookup failed")
    apps = data.get("data") or []
    return any(
        isinstance(item, dict) and str(item.get("id") or "") == app_id
        for item in apps
    )


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


_GENDER_VALUES = frozenset({"male", "female"})

# Requested in one call so a single round trip covers both the CRM display data
# and the address form. Meta silently omits fields the app cannot access.
_USER_PROFILE_FIELDS = "first_name,last_name,profile_pic,gender"


async def get_user_profile(
    config: "FacebookRuntimeConfig", *, psid: str
) -> MessengerUserProfile | None:
    """Return one person's Messenger profile, or ``None`` when unavailable.

    ``None`` covers every "we simply do not get to know this person" outcome:
    an empty object (the app lacks Business Asset User Profile Access, or the
    person made nothing public), a phone-number account (error 2018218), a
    token that is refused the object outright (code 100 / subcode 33, which is
    what a Page token without ``pages_read_engagement`` gets for every PSID),
    and a blank payload. Callers treat all of them the same way — keep whatever
    is already known and address the person neutrally.

    A genuine provider rejection still raises :class:`FacebookOAuthError` so
    token revocation stays distinguishable from missing profile data. As
    everywhere in this module, neither the token nor the raw body is logged.
    """
    data = await _bounded_get(
        f"{config.graph_api_base.rstrip('/')}/{config.graph_api_version}/{psid}",
        params={
            "access_token": config.page_access_token,
            "fields": _USER_PROFILE_FIELDS,
        },
    )
    if isinstance(data.get("error"), dict):
        code = _error_code_from_envelope(data)
        if code == _NO_PROFILE_AVAILABLE_ERROR_CODE:
            return None
        if _is_unreadable_object(data):
            # The token cannot read this person's profile at all — the app lacks
            # Business Asset User Profile Access, or the Page token lacks
            # ``pages_read_engagement``. That is the same "we simply do not get
            # to know this person" outcome as an empty object, so it takes the
            # same path: keep what is already known and stay neutral. Raising
            # here made a standing permission gap look like a transport fault
            # and logged it on every enrichment attempt.
            logger.info(
                "messenger profile lookup refused for this token "
                "(code=%s subcode=%s) — no Business Asset User Profile Access",
                code,
                _error_subcode_from_envelope(data),
            )
            return None
        raise FacebookOAuthError("messenger user profile lookup rejected", code=code)

    def _text(key: str) -> str:
        value = data.get(key)
        return str(value).strip() if isinstance(value, (str, int)) else ""

    gender = _text("gender").lower()
    profile = MessengerUserProfile(
        first_name=_text("first_name"),
        last_name=_text("last_name"),
        profile_pic=_text("profile_pic"),
        gender=gender if gender in _GENDER_VALUES else "",
    )
    if not (profile.display_name or profile.profile_pic or profile.gender):
        return None
    return profile


__all__ = [
    "FacebookPageSummary",
    "FacebookOAuthError",
    "MessengerUserProfile",
    "MESSENGER_PERMISSIONS",
    "get_user_profile",
    "build_authorization_url",
    "exchange_code_for_user_token",
    "list_pages",
    "get_page_access_token",
    "page_is_app_subscribed",
    "probe_page_identity",
    "subscribe_app_to_page",
    "unsubscribe_app_from_page",
    "send_message",
]
