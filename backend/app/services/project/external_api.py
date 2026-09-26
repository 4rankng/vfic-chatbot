"""Per-project external API integration: validation, sealing, egress, throttling.

One project row carries an admin-managed integration (``projects.external_api``):
a base URL, an auth header/scheme, an AES-GCM sealed API key bound to a
project-scoped AEAD context, and a free-text **guide** (the vendor's own
integration document, pasted or uploaded by the admin) that the agent reads to
learn which endpoints exist and how to call them.

The admin fixes the origin; the model chooses only the relative path. That is
the whole security boundary, and it is enforced here:

- ``base_url`` is validated once at save time and re-validated on read, so the
  model can never reach another host — :func:`normalize_endpoint_path` rejects
  any absolute or traversal-shaped path before a request is built.
- Method is limited to ``GET``/``POST``.
- Params are a flat ``str -> str`` map, bounded in count and length, and are
  never interpolated into the path.
- Mutating calls are throttled per (project, method, path) with a
  identical-params dedupe window plus an hour-scale ceiling.

One egress call site (:meth:`ProjectExternalApiService._send`) — the module
imports ``get_http_client``, so the runtime-surface inventory classifies the
whole file as provider transport and a second request site would shift the
reviewed boundary counts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.http import get_http_client
from app.core.redis import get_redis
from app.schemas.projects import ProjectExternalApiUpdate
from app.services.audit_service import record_audit
from app.services.integration_settings.cipher import IntegrationSettingsCipher
from app.services.installation.service import InstallationService
from app.services.project.repository import require_project
from app.shared.domain.errors import (
    BadRequestError,
    InstallationError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# The named pool every project external-API call shares. Callers pass auth
# headers per-request (never at construction) so a rotated key takes effect on
# the next turn.
EXTERNAL_API_CLIENT_NAME = "project_external_api"
EXTERNAL_API_TIMEOUT_SECONDS = 8.0
EXTERNAL_API_MAX_RESPONSE_CHARS = 4000
EXTERNAL_API_MAX_PARAMS = 10
EXTERNAL_API_MAX_PARAM_CHARS = 200
# The guide is injected into the system prompt on every focused turn, so its cap
# is also the per-turn token cost the admin is choosing.
EXTERNAL_API_MAX_GUIDE_CHARS = 16000
EXTERNAL_API_MIN_GUIDE_CHARS = 20
EXTERNAL_API_DEDUPE_SECONDS = 60
EXTERNAL_API_ENDPOINT_CEILING = 60
EXTERNAL_API_ENDPOINT_WINDOW_SECONDS = 60
EXTERNAL_API_ALLOWED_METHODS = ("GET", "POST")
# http is accepted only for a loopback host so a dev/smoke server on
# 127.0.0.1:8799 works without weakening the production rule.
EXTERNAL_API_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Every machine code a caller may surface. Anything else collapses to
# ``invalid_config`` so a BadRequestError detail stays in a closed set.
_CONFIG_ERROR_CODES = frozenset(
    {
        "base_url_credentials",
        "base_url_host",
        "base_url_invalid",
        "base_url_required",
        "base_url_scheme",
        "guide_required",
        "guide_too_long",
        "invalid_config",
    }
)


def normalize_base_url(value: str) -> str:
    """Validate an absolute base URL and return it without a trailing slash.

    ``https`` is required except for a loopback host, where plain ``http`` is
    accepted for local development and smoke runs. Userinfo, a query string and
    a fragment are all rejected — each would let a stored value point somewhere
    other than the origin the admin reviewed.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("base_url_required")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base_url_scheme")
    if parsed.username or parsed.password:
        raise ValueError("base_url_credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url_invalid")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("base_url_host")
    if parsed.scheme == "http" and host not in EXTERNAL_API_LOCAL_HOSTS:
        raise ValueError("base_url_scheme")
    return raw.rstrip("/")


def normalize_endpoint_path(value: str) -> str:
    """Validate a relative request path (``/v1/...``); reject anything absolute.

    This is the origin guard: the model supplies the path, so a value carrying a
    scheme, an authority (``//host``) or a traversal segment must never reach the
    request builder.
    """
    raw = (value or "").strip()
    if not raw or not raw.startswith("/"):
        raise ValueError("path_invalid")
    if "://" in raw or "//" in raw or ".." in raw or "?" in raw or "#" in raw:
        raise ValueError("path_invalid")
    return raw


def normalize_method(value: str) -> str:
    """Fold a model-supplied method onto the allowed set."""
    method = (value or "").strip().upper()
    if method not in EXTERNAL_API_ALLOWED_METHODS:
        raise ValueError("method_not_allowed")
    return method


def api_key_status(value: str) -> dict:
    """Status-only projection for the stored API key.

    Mirrors ``integration_settings._shared._secret_status``: an authorizing
    secret reports whether it is configured and how long it is, and nothing
    derived from the value leaves the process.
    """
    secret = (value or "").strip()
    if not secret:
        return {"configured": False, "preview": None}
    return {"configured": True, "preview": f"{len(secret)} ký tự"}


def sanitize_params(params: object) -> dict[str, str] | None:
    """Coerce model-supplied params into a flat ``str -> str`` mapping.

    ``None`` means "reject": a container value, an over-long value, or more
    parameters than the ceiling. Empty/``None`` values are dropped rather than
    sent as empty strings.
    """
    if params is None:
        return {}
    if not isinstance(params, dict):
        return None
    clean: dict[str, str] = {}
    for raw_key, raw_value in params.items():
        if isinstance(raw_value, (dict, list, tuple, set, frozenset)):
            return None
        text = "" if raw_value is None else str(raw_value).strip()
        if not text:
            continue
        if len(text) > EXTERNAL_API_MAX_PARAM_CHARS:
            return None
        name = str(raw_key).strip()
        if not name:
            continue
        clean[name] = text
    if len(clean) > EXTERNAL_API_MAX_PARAMS:
        return None
    return clean


def config_error_code(exc: ValueError) -> str:
    """Map a pydantic validation failure onto one of the stable machine codes."""
    for error in getattr(exc, "errors", lambda: [])():
        message = str(error["msg"]).removeprefix("Value error, ").strip()
        if message in _CONFIG_ERROR_CODES:
            return message
    return "invalid_config"


class ExternalApiConfig(BaseModel):
    """The stored integration shape; every reader and writer passes through it."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    api_key_encrypted: str = ""
    guide: str = ""

    @model_validator(mode="after")
    def _validate(self) -> ExternalApiConfig:
        if self.base_url.strip():
            self.base_url = normalize_base_url(self.base_url)
        if len(self.guide) > EXTERNAL_API_MAX_GUIDE_CHARS:
            raise ValueError("guide_too_long")
        if self.enabled:
            if not self.base_url.strip():
                raise ValueError("base_url_required")
            # Enabling without a guide would give the model an authenticated
            # egress it has no instructions for — a live footgun, not a config.
            if len(self.guide.strip()) < EXTERNAL_API_MIN_GUIDE_CHARS:
                raise ValueError("guide_required")
        return self


class ExternalApiOutcome(NamedTuple):
    """The only value crossing from the service back into the graph layer."""

    state: str
    project_label: str | None
    path: str
    status_code: int | None
    text: str
    detail: str = ""


@dataclass(frozen=True)
class ExternalApiPromptEntry:
    """One configured project's guide, ready for prompt injection."""

    slug: str
    name: str
    guide: str


def parse_config(raw: object, *, project_id: object | None = None) -> ExternalApiConfig:
    """Parse a stored config dict; an unusable row collapses to the disabled default.

    A row that fails validation is reported as ``enabled=False`` rather than
    raising — a hand-edited or half-migrated value must never break a turn or an
    admin GET.
    """
    if not isinstance(raw, dict):
        return ExternalApiConfig()
    try:
        return ExternalApiConfig(**raw)
    except ValueError:
        logger.warning("project external api config invalid project_id=%s", project_id)
        return ExternalApiConfig()


class ProjectExternalApiService:
    """Admin-facing CRUD plus the single outbound call path for one project."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Settings | None = None,
        cipher: IntegrationSettingsCipher | None = None,
    ) -> None:
        self.db = db
        self._cipher = cipher or IntegrationSettingsCipher(settings)

    @staticmethod
    def _context(project_id: uuid.UUID) -> str:
        return f"project-external-api:{project_id}"

    def _parse(self, project: Any, project_id: uuid.UUID) -> ExternalApiConfig:
        return parse_config(project.external_api, project_id=project_id)

    async def _chatbot_blockers(
        self, project: Any, config: ExternalApiConfig
    ) -> list[str]:
        """Stable codes for the gates that fail closed before ``call_project_api``.

        ``config.enabled`` already implies a valid https ``base_url`` and a
        guide of at least ``EXTERNAL_API_MIN_GUIDE_CHARS`` (enforced on save;
        an invalid row parses as disabled), so ``integration_disabled`` covers
        both. The capability and persona checks mirror the fail-closed gates in
        ``app/graph/runtime_policy.py`` and the tool registry build; the
        per-conversation page scope is deliberately not part of this projection.
        """
        blockers: list[str] = []
        if not config.enabled:
            blockers.append("integration_disabled")
        if not project.is_active:
            blockers.append("project_inactive")
        try:
            installation = InstallationService(self.db)
            active = await installation.require_active()
            if "knowledge" not in active.revision.capability_ids:
                blockers.append("knowledge_capability_missing")
            persona = await installation.repo.get_persona_version(
                active.revision.persona_version_id
            )
            if persona is None or not (persona.body_md or "").strip():
                blockers.append("persona_missing")
        except InstallationError:
            blockers.append("installation_required")
        except Exception:  # noqa: BLE001 — an admin read must never 500 on authority lookup
            logger.warning("chatbot readiness unavailable project_id=%s", project.id)
            blockers.append("readiness_unavailable")
        return blockers

    async def admin_view(self, project_id: uuid.UUID) -> dict:
        """Masked projection for the admin UI — the key itself never appears."""
        project = await require_project(self.db, project_id)
        config = self._parse(project, project_id)
        blockers = await self._chatbot_blockers(project, config)
        return {
            "enabled": config.enabled,
            "base_url": config.base_url,
            "auth_header": config.auth_header,
            "auth_scheme": config.auth_scheme,
            "guide": config.guide,
            "api_key": api_key_status(self._decrypt(config.api_key_encrypted, project_id)),
            "chatbot_readiness": {"ready": not blockers, "blockers": blockers},
        }

    async def replace(
        self, project_id: uuid.UUID, payload: ProjectExternalApiUpdate, actor: Any
    ) -> dict:
        """Replace the stored integration; ``api_key`` is tri-state.

        Absent/``None`` keeps the stored ciphertext, ``""`` clears it, anything
        else is sealed under this project's AEAD context so a row copied to
        another project fails to decrypt.
        """
        project = await require_project(self.db, project_id)
        current = self._parse(project, project_id)
        data = payload.model_dump(exclude_unset=True)
        marker = data.pop("api_key", None)
        ciphertext = current.api_key_encrypted
        if marker is not None:
            secret = str(marker).strip()
            ciphertext = (
                self._cipher.encrypt_with_context(secret, self._context(project_id))
                if secret
                else ""
            )
        try:
            config = ExternalApiConfig(**data, api_key_encrypted=ciphertext)
        except ValueError as exc:
            raise BadRequestError(config_error_code(exc)) from None
        project.external_api = config.model_dump()
        await record_audit(
            self.db,
            action="project_external_api_updated",
            actor_id=getattr(actor, "id", None),
            target_type="project",
            target_id=str(project_id),
        )
        await self.db.commit()
        return await self.admin_view(project_id)

    async def test(
        self,
        project_id: uuid.UUID,
        *,
        method: str,
        path: str,
        params: dict | None,
    ) -> ExternalApiOutcome:
        """Admin-triggered mirror of the chatbot's one call.

        Same validation, dedupe/throttle and egress as ``invoke`` — the point
        is to prove the stored integration works through the bot's own path.
        """
        project = await require_project(self.db, project_id)
        config = self._parse(project, project_id)
        if not config.enabled:
            return ExternalApiOutcome("not_configured", None, path.strip(), None, "")
        api_key = self._decrypt(config.api_key_encrypted, project_id)
        if config.api_key_encrypted and not api_key:
            return ExternalApiOutcome(
                "error", None, path.strip(), None, "", "key_undecryptable"
            )
        return await self.invoke(
            project_id, config, api_key, method=method, path=path, params=params
        )

    async def runtime(self, project_id: uuid.UUID) -> tuple[ExternalApiConfig, str] | None:
        """The callable config + decrypted key, or ``None`` when unusable."""
        try:
            project = await require_project(self.db, project_id)
        except NotFoundError:
            return None
        config = self._parse(project, project_id)
        if not config.enabled:
            return None
        if config.api_key_encrypted:
            try:
                api_key = self._cipher.decrypt_with_context(
                    config.api_key_encrypted, self._context(project_id)
                )
            except InvalidTag:
                logger.warning(
                    "project external api key undecryptable project_id=%s", project_id
                )
                return None
        else:
            api_key = ""
        return config, api_key

    def _decrypt(self, stored: str, project_id: uuid.UUID) -> str:
        if not stored:
            return ""
        try:
            return self._cipher.decrypt_with_context(stored, self._context(project_id))
        except InvalidTag:
            logger.warning("project external api key undecryptable project_id=%s", project_id)
            return ""

    async def invoke(
        self,
        project_id: uuid.UUID,
        config: ExternalApiConfig | None,
        api_key: str,
        *,
        method: str,
        path: str,
        params: dict | None,
    ) -> ExternalApiOutcome:
        """Call one path on the project's configured origin exactly once."""
        outcome_path = (path or "").strip()
        if config is None or not config.enabled:
            return ExternalApiOutcome("not_configured", None, outcome_path, None, "")
        try:
            clean_method = normalize_method(method)
        except ValueError as exc:
            return ExternalApiOutcome(
                "invalid_request", None, outcome_path, None, "", str(exc)
            )
        try:
            clean_path = normalize_endpoint_path(outcome_path)
        except ValueError as exc:
            return ExternalApiOutcome(
                "invalid_request", None, outcome_path, None, "", str(exc)
            )
        sanitized = sanitize_params(params)
        if sanitized is None:
            return ExternalApiOutcome(
                "invalid_request", None, clean_path, None, "", "invalid_params"
            )
        if clean_method != "GET" and not await self._consume_write(
            project_id, clean_method, clean_path, sanitized
        ):
            return ExternalApiOutcome("rate_limited", None, clean_path, None, "")
        started = time.monotonic()
        try:
            response = await self._send(
                config, api_key, clean_method, clean_path, sanitized
            )
        except httpx.TimeoutException:
            self._log_call(project_id, clean_method, clean_path, None, started, "timeout")
            return ExternalApiOutcome("error", None, clean_path, None, "", "timeout")
        except (httpx.HTTPError, OSError):
            self._log_call(project_id, clean_method, clean_path, None, started, "network_error")
            return ExternalApiOutcome("error", None, clean_path, None, "", "network_error")
        status = response.status_code
        self._log_call(project_id, clean_method, clean_path, status, started, "")
        if status >= 400:
            # No response body on an error status: it can echo the submitted
            # parameters back and would be logged or repeated to the user.
            return ExternalApiOutcome("error", None, clean_path, status, "", f"status_{status}")
        return ExternalApiOutcome(
            "ok", None, clean_path, status, response.text[:EXTERNAL_API_MAX_RESPONSE_CHARS]
        )

    async def _send(
        self,
        config: ExternalApiConfig,
        api_key: str,
        method: str,
        path: str,
        params: dict[str, str],
    ) -> httpx.Response:
        """The module's single outbound request site."""
        headers: dict[str, str] = {}
        if api_key and config.auth_header:
            headers[config.auth_header] = f"{config.auth_scheme} {api_key}".strip()
        client = await get_http_client(
            EXTERNAL_API_CLIENT_NAME, timeout=EXTERNAL_API_TIMEOUT_SECONDS
        )
        return await client.request(
            method,
            f"{config.base_url}{path}",
            params=params if method == "GET" else None,
            json=None if method == "GET" else params,
            headers=headers,
            timeout=EXTERNAL_API_TIMEOUT_SECONDS,
        )

    def _log_call(
        self,
        project_id: uuid.UUID,
        method: str,
        path: str,
        status: int | None,
        started: float,
        detail: str,
    ) -> None:
        """Log the call shape only — never the query, params, key or body."""
        logger.info(
            "project external api call project_id=%s method=%s path=%s status=%s "
            "elapsed_ms=%d detail=%s",
            project_id,
            method,
            path,
            status if status is not None else "-",
            int((time.monotonic() - started) * 1000),
            detail or "ok",
        )

    async def _consume_write(
        self,
        project_id: uuid.UUID,
        method: str,
        path: str,
        params: dict[str, str],
    ) -> bool:
        """Two buckets for a mutating call: identical-params dedupe, then ceiling."""
        digest = hashlib.sha256(
            json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        scoped = f"{project_id}:{method}:{path}"
        if not await self._consume(
            f"extapi:dedupe:{scoped}:{digest}",
            limit=1,
            window=EXTERNAL_API_DEDUPE_SECONDS,
        ):
            return False
        return await self._consume(
            f"extapi:ceiling:{scoped}",
            limit=EXTERNAL_API_ENDPOINT_CEILING,
            window=EXTERNAL_API_ENDPOINT_WINDOW_SECONDS,
        )

    async def _consume(self, key: str, *, limit: int, window: int) -> bool:
        """Fixed-window admission check; fail-open when Redis is unavailable.

        The key is a digest plus identifiers — never the API key and never a
        plaintext parameter value.
        """
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window)
            return count <= limit
        except Exception as exc:  # noqa: BLE001 — a Redis hiccup must not block the turn
            logger.warning(
                "project external api throttle skipped error_type=%s", type(exc).__name__
            )
            return True


__all__ = [
    "EXTERNAL_API_ALLOWED_METHODS",
    "EXTERNAL_API_CLIENT_NAME",
    "EXTERNAL_API_DEDUPE_SECONDS",
    "EXTERNAL_API_ENDPOINT_CEILING",
    "EXTERNAL_API_ENDPOINT_WINDOW_SECONDS",
    "EXTERNAL_API_LOCAL_HOSTS",
    "EXTERNAL_API_MAX_GUIDE_CHARS",
    "EXTERNAL_API_MAX_PARAMS",
    "EXTERNAL_API_MAX_PARAM_CHARS",
    "EXTERNAL_API_MAX_RESPONSE_CHARS",
    "EXTERNAL_API_MIN_GUIDE_CHARS",
    "EXTERNAL_API_TIMEOUT_SECONDS",
    "ExternalApiConfig",
    "ExternalApiOutcome",
    "ExternalApiPromptEntry",
    "ProjectExternalApiService",
    "api_key_status",
    "config_error_code",
    "normalize_base_url",
    "normalize_endpoint_path",
    "normalize_method",
    "parse_config",
    "sanitize_params",
]
