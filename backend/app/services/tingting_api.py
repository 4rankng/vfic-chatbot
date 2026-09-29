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

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.core.redis import get_redis
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
# The optional pin naming the one Zalo OA allowed to run the reset flow. The flow
# is never offered off ``zalo_oa``; this row narrows it to a single OA account
# (``""`` = any connected OA), which is how the operator keeps it on the
# TingTing OA and off the recruitment Bot.
TINGTING_RESET_OA_ID_SETTING = "tingting_reset_oa_id"
# The escalation hotline the support OA quotes whenever the bot cannot help
# in-chat (operator rule 2026-09-29: nobody works that OA). Admin-editable;
# seeded with the owner-approved number by Alembic 0058 and re-read every turn,
# so an edit takes effect on the next message without a deploy.
TINGTING_HOTLINE_SETTING = "tingting_hotline"
TINGTING_API_CLIENT_NAME = "tingting_api"
TINGTING_API_AUTH_HEADER = "X-API-Key"
# The TingTing app's origin only — the ``/api/v1`` prefix belongs to the path
# the guide documents (``/api/v1/integration/...``), so carrying it here too
# would request ``/api/v1/api/v1/...`` and every call would 404. An operator may
# point a dev or smoke deployment elsewhere by setting ``tingting_api_base``;
# the value is re-validated on read, so a bad override falls back to this origin.
TINGTING_API_BASE_DEFAULT = "https://tingting.vip"
TINGTING_API_LABEL = "TingTing"

# The reset API's only read-only endpoint. Everything else the model can reach
# (otp / verify / reset) mutates account state and keeps the identical-params
# dedupe; the lookup must stay repeatable, because step 2 of the guide has the
# model re-read the record to compare the employee's name/CCCD before an OTP is
# sent — a second identical lookup is a legitimate retry, not a duplicate write.
TINGTING_READ_ONLY_PATHS: frozenset[str] = frozenset({"/api/v1/integration/employee/lookup"})

# The reset flow spans several turns, but the agent's message list does not: a
# ``session_id`` handed to the model on the OTP turn is gone by the turn the
# employee replies with the code, and the model then guesses — production sent
# ``password-reset/verify`` with a stale session and got HTTP 400. The session
# therefore lives server-side, keyed by the employee's phone digits, for the life
# of the flow. 15 minutes covers a 600 s session plus the employee's reading time.
TINGTING_FLOW_TTL_SECONDS = 900
TINGTING_FLOW_KEY_PREFIX = "tingting:flow"


def _flow_key(phone: str) -> str:
    """Redis key for one employee's flow: a phone digest, never the number.

    The digits are canonicalised the same way the identity tool canonicalises a
    submitted number (``+84`` folded onto the local ``0``), or the same employee
    would get a different key — and lose the OTP session — by typing the number
    in the international form.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) > 9 and digits.startswith("84"):
        digits = "0" + digits[2:]
    return f"{TINGTING_FLOW_KEY_PREFIX}:{hashlib.sha256(digits.encode('utf-8')).hexdigest()[:32]}"


class TingtingFlowStore:
    """Per-employee reset-flow state: verified flag, OTP session, reset token.

    Read-modify-write on one Redis key; ``save`` merges so a step cannot drop
    what an earlier step stored. Fail-open like the egress throttle: a Redis
    outage degrades to "no session", which every caller reports honestly instead
    of guessing a session id.
    """

    async def load(self, phone: str) -> dict[str, Any]:
        try:
            raw = await get_redis().get(_flow_key(phone))
        except Exception as exc:  # noqa: BLE001 — state read must not break a turn
            logger.warning("tingting flow read skipped error_type=%s", type(exc).__name__)
            return {}
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    async def save(self, phone: str, state: dict[str, Any]) -> dict[str, Any]:
        merged = {**await self.load(phone), **state}
        try:
            await get_redis().set(
                _flow_key(phone),
                json.dumps(merged, ensure_ascii=False),
                ex=TINGTING_FLOW_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — a cache write must not 500 a turn
            logger.warning("tingting flow write skipped error_type=%s", type(exc).__name__)
        return merged

    async def clear(self, phone: str) -> None:
        try:
            await get_redis().delete(_flow_key(phone))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tingting flow clear skipped error_type=%s", type(exc).__name__)


# Identity verification may not succeed inside one 15-minute flow window: an
# employee can give up and return the next day with the corrected CCCD. The
# failed-attempt counter therefore lives under its own key and its own TTL, long
# enough to survive a multi-turn struggle but bounded so an abandoned count
# cannot outlive the conversation that earned it.
TINGTING_VERIFY_MAX_ATTEMPTS = 3
TINGTING_VERIFY_ATTEMPTS_TTL_SECONDS = 86400
TINGTING_VERIFY_KEY_PREFIX = "tingting:verify_attempts"


def _verify_attempts_key(scope: str) -> str:
    """Redis key for one conversation's failed-verification count.

    The scope is the conversation id (a UUID string the caller already holds);
    it is digested like the flow key so the raw identifier never becomes a
    Redis key segment.
    """
    digest = hashlib.sha256(str(scope or "").encode("utf-8")).hexdigest()[:32]
    return f"{TINGTING_VERIFY_KEY_PREFIX}:{digest}"


class TingtingVerifyAttemptsStore:
    """Per-conversation failed-identity-verification counter.

    Counts the tries an employee has spent on ``verify_tingting_identity`` in
    this conversation, so the flow can stop asking after
    :data:`TINGTING_VERIFY_MAX_ATTEMPTS` failures and hand off to a consultant
    instead. Fail-open like :class:`TingtingFlowStore`: a Redis outage degrades
    to "no count recorded", which leaves the flow unlimited rather than locking
    a legitimate employee out of the reset flow.
    """

    async def count(self, scope: str) -> int:
        try:
            raw = await get_redis().get(_verify_attempts_key(scope))
        except Exception as exc:  # noqa: BLE001 — a counter read must not break a turn
            logger.warning("tingting verify count skipped error_type=%s", type(exc).__name__)
            return 0
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0

    async def record_failure(self, scope: str) -> int:
        """Count one failed verification and return the running total."""
        try:
            key = _verify_attempts_key(scope)
            total = int(await get_redis().incr(key))
            await get_redis().expire(key, TINGTING_VERIFY_ATTEMPTS_TTL_SECONDS)
            return max(1, total)
        except Exception as exc:  # noqa: BLE001 — a counter write must not 500 a turn
            logger.warning("tingting verify failure record skipped error_type=%s", type(exc).__name__)
            return 0

    async def reset(self, scope: str) -> None:
        try:
            await get_redis().delete(_verify_attempts_key(scope))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tingting verify reset skipped error_type=%s", type(exc).__name__)


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

    async def reset_oa_id(self) -> str:
        """The OA account key allowed to run the reset flow (``""`` = any OA)."""
        row = await self.db.get(IntegrationSetting, TINGTING_RESET_OA_ID_SETTING)
        if row is None:
            return ""
        return self._decrypt(str(getattr(row, "encrypted_value", "") or "")).strip()

    async def hotline(self) -> str:
        """The escalation hotline quoted by the support OA (``""`` = unset).

        The Alembic seed stores the value as plaintext in the settings column,
        which the cipher fails soft on (only ``v1:``-prefixed rows decrypt), so
        the seeded number and an admin-encrypted edit both read back here.
        """
        row = await self.db.get(IntegrationSetting, TINGTING_HOTLINE_SETTING)
        if row is None:
            return ""
        return self._decrypt(str(getattr(row, "encrypted_value", "") or "")).strip()

    async def admin_view(self) -> dict:
        """Status-only projection — the key itself never appears."""
        api_key = self._decrypt(await self._stored_ciphertext())
        return {
            "api_key": _secret_status(api_key),
            "configured": bool(api_key),
            "base_url": resolve_base_url(self.settings),
            "auth_header": TINGTING_API_AUTH_HEADER,
            "reset_oa_id": await self.reset_oa_id(),
            "hotline": await self.hotline(),
        }

    async def replace_hotline(self, value: Any, *, actor_id: Any = None) -> dict:
        """Persist the escalation hotline; ``""`` clears it (the bot degrades to
        the no-number reply). ``None`` keeps the stored value."""
        if value is None:
            return await self.admin_view()
        number = str(value).strip()
        row = await self.db.get(IntegrationSetting, TINGTING_HOTLINE_SETTING)
        encrypted = self._cipher.encrypt(number) if number else ""
        if row is None:
            self.db.add(
                IntegrationSetting(
                    key=TINGTING_HOTLINE_SETTING,
                    encrypted_value=encrypted,
                    is_secret=False,
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
            payload={"hotline_configured": bool(number)},
        )
        await self.db.commit()
        return await self.admin_view()

    async def replace_reset_oa_id(self, value: Any, *, actor_id: Any = None) -> dict:
        """Persist the reset-flow OA pin; ``""`` allows any connected OA."""
        if value is None:
            return await self.admin_view()
        pin = str(value).strip()
        row = await self.db.get(IntegrationSetting, TINGTING_RESET_OA_ID_SETTING)
        encrypted = self._cipher.encrypt(pin) if pin else ""
        if row is None:
            self.db.add(
                IntegrationSetting(
                    key=TINGTING_RESET_OA_ID_SETTING,
                    encrypted_value=encrypted,
                    is_secret=False,
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
            payload={"reset_oa_id_configured": bool(pin)},
        )
        await self.db.commit()
        return await self.admin_view()

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
        decision = await consume_write_quota(
            f"tingting:{clean_method}:{clean_path}",
            sanitized,
            dedupe=clean_method != "GET" and clean_path not in TINGTING_READ_ONLY_PATHS,
        )
        if not decision.allowed:
            state = "duplicate_request" if decision.reason == "duplicate" else "rate_limited"
            return ExternalApiOutcome(state, None, clean_path, None, "")
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
    "TINGTING_HOTLINE_SETTING",
    "TINGTING_RESET_OA_ID_SETTING",
    "TINGTING_READ_ONLY_PATHS",
    "TINGTING_FLOW_KEY_PREFIX",
    "TINGTING_FLOW_TTL_SECONDS",
    "TINGTING_VERIFY_ATTEMPTS_TTL_SECONDS",
    "TINGTING_VERIFY_KEY_PREFIX",
    "TINGTING_VERIFY_MAX_ATTEMPTS",
    "TingtingApiRuntime",
    "TingtingApiService",
    "TingtingFlowStore",
    "TingtingVerifyAttemptsStore",
    "resolve_base_url",
]
