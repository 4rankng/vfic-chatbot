"""Deployment-wide TingTing integration: one API key, one egress site.

The employee password-reset flow belongs to the TingTing app itself, not to a
project: any employee who can prove identity (full name + CCCD + mobile) gets an
OTP on the registered mobile. The admin therefore configures exactly one thing —
the ``X-API-Key`` — in the settings page, and the workflow guide lives in code
(:mod:`app.graph.tingting_guide`) because it is one workflow for every tenant.

Security boundary (shared with the per-project integration; validation, caps and
the Redis quota come from ``app.services.project.external_api``):

- the origin is a code constant (:data:`TINGTING_API_BASE_DEFAULT`) or a
  validated operator override on ``Settings``; the model never supplies a host;
- :func:`normalize_endpoint_path` rejects absolute/traversal paths;
- method is limited to ``GET``/``POST``; params are a flat, bounded ``str -> str``
  map and are never interpolated into the path;
- mutating calls go through the shared identical-params dedupe + ceiling;
- the key is stored AES-GCM-encrypted and never leaves the process.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.models.integration import IntegrationSetting
from app.services.audit_service import record_audit
from app.services.external_api_core import (
    EXTERNAL_API_MAX_RESPONSE_CHARS,
    EXTERNAL_API_TIMEOUT_SECONDS,
    ExternalApiOutcome,
    consume_write_quota,
    normalize_base_url,
    normalize_endpoint_path,
    normalize_method,
    sanitize_params,
)
from app.services.integration_settings._shared import _secret_status
from app.services.integration_settings.cipher import IntegrationSettingsCipher

logger = logging.getLogger(__name__)

# The integration row the settings page writes. One key, no per-tenant content.
TINGTING_API_KEY_SETTING = "tingting_api_key"
TINGTING_API_CLIENT_NAME = "tingting_api"
TINGTING_API_AUTH_HEADER = "X-API-Key"
# Where the TingTing app serves the reset API. An operator may point a dev or
# smoke deployment elsewhere by setting ``tingting_api_base``; the value is
# re-validated on read, so a bad override falls back to this origin.
TINGTING_API_BASE_DEFAULT = "https://tingting.vip/api/v1"
TINGTING_API_LABEL = "TingTing"


@dataclass(frozen=True)
class TingtingApiRuntime:
    """The callable configuration: a fixed origin plus the decrypted key."""

    base_url: str
    api_key: str


def resolve_base_url(settings: Settings | None = None) -> str:
    """The validated origin for every TingTing call (never model-supplied)."""
    candidate = str(getattr(settings, "tingting_api_base", "") or "").strip()
    if not candidate:
        return TINGTING_API_BASE_DEFAULT
    try:
        return normalize_base_url(candidate)
    except ValueError as exc:
        logger.warning("tingting api base_url rejected code=%s", exc)
        return TINGTING_API_BASE_DEFAULT


class TingtingApiService:
    """Admin-facing key CRUD plus the single outbound call path."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        cipher: IntegrationSettingsCipher | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self._cipher = cipher or IntegrationSettingsCipher(self.settings)

    # ── configuration ───────────────────────────────────────────────────────

    async def _stored_ciphertext(self) -> str:
        row = await self.db.get(IntegrationSetting, TINGTING_API_KEY_SETTING)
        if row is None:
            return ""
        return str(getattr(row, "encrypted_value", "") or "")

    def _decrypt(self, stored: str) -> str:
        if not stored:
            return ""
        try:
            return self._cipher.decrypt(stored).strip()
        except InvalidTag:
            logger.warning("tingting api key undecryptable")
            return ""

    async def runtime(self) -> TingtingApiRuntime | None:
        """The callable config, or ``None`` when no usable key is configured."""
        api_key = self._decrypt(await self._stored_ciphertext())
        if not api_key:
            return None
        return TingtingApiRuntime(base_url=resolve_base_url(self.settings), api_key=api_key)

    async def configured(self) -> bool:
        """Whether the integration is configured — the prompt gate."""
        try:
            return await self.runtime() is not None
        except Exception as exc:  # noqa: BLE001 — a prompt gate must never break a turn
            logger.warning(
                "tingting api configuration read failed error_type=%s", type(exc).__name__
            )
            return False

    async def admin_view(self) -> dict:
        """Status-only projection — the key itself never appears."""
        api_key = self._decrypt(await self._stored_ciphertext())
        return {
            "api_key": _secret_status(api_key),
            "configured": bool(api_key),
            "base_url": resolve_base_url(self.settings),
            "auth_header": TINGTING_API_AUTH_HEADER,
        }

    async def replace_key(self, value: Any, *, actor_id: Any = None) -> dict:
        """Persist the key; ``""`` clears it. ``None`` keeps the stored value."""
        if value is None:
            return await self.admin_view()
        secret = str(value).strip()
        row = await self.db.get(IntegrationSetting, TINGTING_API_KEY_SETTING)
        encrypted = self._cipher.encrypt(secret) if secret else ""
        if row is None:
            self.db.add(
                IntegrationSetting(
                    key=TINGTING_API_KEY_SETTING,
                    encrypted_value=encrypted,
                    is_secret=True,
                    updated_by=actor_id,
                )
            )
        else:
            row.encrypted_value = encrypted
            row.updated_by = actor_id
        await record_audit(
            self.db,
            action="update_tingting_integration_settings",
            actor_id=actor_id,
            target_type="integration_settings",
            target_id="tingting",
            payload={"api_key_configured": bool(secret)},
        )
        await self.db.commit()
        return await self.admin_view()

    # ── the one call path ───────────────────────────────────────────────────

    async def invoke(
        self,
        runtime: TingtingApiRuntime | None,
        *,
        method: str,
        path: str,
        params: dict | None,
    ) -> ExternalApiOutcome:
        """Call one path on the TingTing origin exactly once."""
        outcome_path = (path or "").strip()
        if runtime is None:
            return ExternalApiOutcome("not_configured", None, outcome_path, None, "")
        try:
            clean_method = normalize_method(method)
        except ValueError as exc:
            return ExternalApiOutcome("invalid_request", None, outcome_path, None, "", str(exc))
        try:
            clean_path = normalize_endpoint_path(outcome_path)
        except ValueError as exc:
            return ExternalApiOutcome("invalid_request", None, outcome_path, None, "", str(exc))
        sanitized = sanitize_params(params)
        if sanitized is None:
            return ExternalApiOutcome("invalid_request", None, clean_path, None, "", "invalid_params")
        if clean_method != "GET" and not await consume_write_quota(
            f"tingting:{clean_method}:{clean_path}", sanitized
        ):
            return ExternalApiOutcome("rate_limited", None, clean_path, None, "")
        started = time.monotonic()
        try:
            response = await self._send(runtime, clean_method, clean_path, sanitized)
        except httpx.TimeoutException:
            self._log_call(clean_method, clean_path, None, started, "timeout")
            return ExternalApiOutcome("error", None, clean_path, None, "", "timeout")
        except (httpx.HTTPError, OSError):
            self._log_call(clean_method, clean_path, None, started, "network_error")
            return ExternalApiOutcome("error", None, clean_path, None, "", "network_error")
        status = response.status_code
        self._log_call(clean_method, clean_path, status, started, "")
        if status >= 400:
            # No response body on an error status: it can echo the submitted
            # parameters back and would be repeated to the user.
            return ExternalApiOutcome("error", None, clean_path, status, "", f"status_{status}")
        return ExternalApiOutcome(
            "ok",
            TINGTING_API_LABEL,
            clean_path,
            status,
            response.text[:EXTERNAL_API_MAX_RESPONSE_CHARS],
        )

    async def _send(
        self,
        runtime: TingtingApiRuntime,
        method: str,
        path: str,
        params: dict[str, str],
    ) -> httpx.Response:
        """This module's single outbound request site."""
        client = await get_http_client(
            TINGTING_API_CLIENT_NAME, timeout=EXTERNAL_API_TIMEOUT_SECONDS
        )
        return await client.request(
            method,
            f"{runtime.base_url}{path}",
            params=params if method == "GET" else None,
            json=None if method == "GET" else params,
            headers={TINGTING_API_AUTH_HEADER: runtime.api_key},
            timeout=EXTERNAL_API_TIMEOUT_SECONDS,
        )

    def _log_call(
        self,
        method: str,
        path: str,
        status: int | None,
        started: float,
        detail: str,
    ) -> None:
        """Log the call shape only — never the params, key or body."""
        logger.info(
            "tingting api call method=%s path=%s status=%s elapsed_ms=%d detail=%s",
            method,
            path,
            status if status is not None else "-",
            int((time.monotonic() - started) * 1000),
            detail or "ok",
        )


__all__ = [
    "TINGTING_API_AUTH_HEADER",
    "TINGTING_API_BASE_DEFAULT",
    "TINGTING_API_CLIENT_NAME",
    "TINGTING_API_KEY_SETTING",
    "TINGTING_API_LABEL",
    "TingtingApiRuntime",
    "TingtingApiService",
    "resolve_base_url",
]
