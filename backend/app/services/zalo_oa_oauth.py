"""Zalo Official Account OAuth client (scan-to-connect).

Implements the OA-authorization grant (NOT social login): an admin scans a QR on
Zalo's /v4/oa/permission page and approves; we exchange the returned code for an
OA access token (1h) + refresh token (3 months, single-use, rotates on each use).

The /oa/ segments are load-bearing and distinguish this from the social-login flow
at /v4/permission: the OA grant yields a token that lets the app send/receive AS
the Official Account, not a user-identity token.

Endpoints (verified against Zalo for Developers OA docs + third-party integrators):
- Authorize: https://oauth.zaloapp.com/v4/oa/permission?app_id=&redirect_uri=&state=
- Token:     POST https://oauth.zaloapp.com/v4/oa/access_token  (secret_key header,
             application/x-www-form-urlencoded body; same endpoint for grant_type
             authorization_code and refresh_token).
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import httpx

ZALO_OAUTH_BASE = "https://oauth.zaloapp.com/v4/oa"
PERMISSION_PATH = "/permission"
ACCESS_TOKEN_PATH = "/access_token"


@dataclass(frozen=True)
class TokenSet:
    """Parsed token-endpoint response. ``expires_in`` is seconds (Zalo: 3600)."""

    access_token: str
    refresh_token: str
    expires_in: int


class ZaloOAOAuthError(RuntimeError):
    """Raised when Zalo's token endpoint returns an error or an unusable payload."""


class ZaloOAOAuthClient:
    """Talks to Zalo's OA OAuth token endpoints.

    The app ``secret_key`` is sent in the ``secret_key`` request header — never in
    the URL or body.
    """

    def __init__(
        self,
        app_id: str,
        secret_key: str,
        *,
        timeout: float = 20.0,
    ) -> None:
        self._app_id = app_id
        self._secret_key = secret_key
        self._timeout = timeout

    def build_authorize_url(self, redirect_uri: str, state: str) -> str:
        """The popup URL. Zalo renders the QR on this page."""
        params = urllib.parse.urlencode(
            {
                "app_id": self._app_id,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{ZALO_OAUTH_BASE}{PERMISSION_PATH}?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        """Redeem a one-time authorization code (10-min TTL) for a token set."""
        return await self._post_token(
            {
                "app_id": self._app_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        """Rotate a refresh token for a fresh access+refresh pair.

        Zalo refresh tokens are single-use: the returned ``refresh_token`` is the
        NEXT one and must replace the stored value.
        """
        return await self._post_token(
            {
                "app_id": self._app_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    async def _post_token(self, form: dict[str, str]) -> TokenSet:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{ZALO_OAUTH_BASE}{ACCESS_TOKEN_PATH}",
                data=form,
                headers={
                    "secret_key": self._secret_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ZaloOAOAuthError(
                f"non-JSON token response (HTTP {resp.status_code}): {resp.text!r}"
            ) from exc
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        if not access_token or not refresh_token or expires_in is None:
            err = payload.get("error")
            desc = payload.get("error_description") or payload
            raise ZaloOAOAuthError(f"token endpoint error: {err} / {desc}")
        return TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(expires_in),
        )
