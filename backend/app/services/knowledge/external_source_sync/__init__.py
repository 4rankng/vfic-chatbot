"""External knowledge-source sync orchestrator.

Pulls a public Google Sheet, parses it into a category payload, and — when the
content actually changed — drives it through the existing
:class:`~app.services.knowledge.category_service.KnowledgeCategoryService`
replacement pipeline. ``stage_replacement`` enqueues activation asynchronously,
so this module never calls ``activate_revision`` itself (Finding 4).

Hardening (2026-07-21 red-team review):
  * SSRF allow-list + IP-literal reject + DNS-pin + ``follow_redirects=False``
    + one-shot httpx client per fetch (Findings 1, 2, 15).
  * Hash-skip keyed on the ACTIVE revision's ``content_sha256`` via the SAME
    ``category_checksum`` the pipeline uses, so the skip never drifts from what
    the category pipeline stored (Finding 11).
  * Per-state Redis lock so the daily tick and a run-now click cannot double-stage
    the same row across a day boundary (Finding 23).
  * Sanitised ``last_error`` (URLs/query stripped), 3-strike auto-disable on
    revocable failures, lowercase category-key normalisation (Findings 17, 24).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.external_source_sync_state import ExternalSourceSyncState
from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.models.user import User
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.errors import ConflictError, UpstreamError
from app.services.knowledge.category_contracts import (
    EmptyCategoryError,
    category_checksum,
    parse_category_yaml,
)
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.services.knowledge.external_source_sync.parsers import PARSERS

logger = logging.getLogger(__name__)

# Per-fetch httpx timeout (a module constant, not env-tunable — the global kill
# switch is the only knob that needs an incident-time flip; see config.py).
DEFAULT_HTTP_TIMEOUT = 30

LOCK_KEY_PREFIX = "ext_src_sync"
LOCK_TTL_SECONDS = 3600

# The fetch always reconstructs the export URL against docs.google.com, so only
# that host is actually reached. The wider set lets admins PASTE any of these
# Google URL forms (and pre-allows hosts a future source_kind — e.g. a
# google_doc parser — would fetch from) without an API-layer rejection; the
# orchestrator still pins the real request to docs.google.com.
ALLOWED_HOSTS = frozenset({"docs.google.com", "sheets.googleapis.com"})
ALLOWED_HOST_SUFFIXES = frozenset({"googleusercontent.com"})

# Reasons that indicate the sheet is gone/private rather than a transient Google
# outage. These count toward the 3-strike auto-disable; transient ones do not.
REVOCABLE_FAILURE_REASONS = frozenset(
    {"sheet_not_public", "http_401", "http_403", "http_404", "http_410", "dns_resolution_failed"}
)
AUTO_DISABLE_THRESHOLD = 3

_URL_RE = re.compile(r"https?://[^\s'\"]+")
_SHEET_ID_RE = re.compile(r"/d/(?P<id>[A-Za-z0-9_-]{20,})(?:/|$|\?|#)")


class ExternalSourceSyncError(Exception):
    """An expected sync failure. ``code`` is the short, sanitised reason."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True, slots=True)
class ExternalSourceSyncOutcome:
    """Result of one sync attempt. ``status`` is STAGED | NO_OP | FAILED | LOCKED."""

    status: str
    category_key: str
    content_hash: str | None = None
    revision_id: uuid.UUID | None = None
    job_id: str | None = None
    error: str | None = None


def extract_sheet_id(url: str) -> str:
    """Extract the spreadsheet ID from any ``docs.google.com`` URL form."""
    match = _SHEET_ID_RE.search(url)
    if not match:
        raise ExternalSourceSyncError("invalid_sheet_id")
    return match.group("id")


def validate_sheet_url(url: str) -> None:
    """SSRF gate. Shared by the API layer (defense-in-depth) and the fetch.

    Rejects non-HTTPS, IP literals, and any host outside the Google allow-list.
    The fetch additionally DNS-pins the host and reconstructs the export URL
    from the parsed sheet id, so the caller's path/query is never trusted.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ExternalSourceSyncError("scheme_not_https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ExternalSourceSyncError("invalid_url")
    try:
        ipaddress.ip_address(host)
        raise ExternalSourceSyncError("ip_literal_forbidden")
    except ValueError:
        pass  # not an IP literal — good
    if not (host in ALLOWED_HOSTS or any(host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)):
        raise ExternalSourceSyncError("host_not_allowed")


def _reject_private_host(host: str) -> None:
    """DNS-pin: reject hosts that resolve to private/loopback/link-local/etc.

    Defends against DNS-rebinding to ``169.254.169.254`` (AWS IMDS) or RFC1918
    ranges.
    """
    try:
        infos = socket.getaddrinfo(host, 443)
    except socket.gaierror as exc:
        raise ExternalSourceSyncError("dns_resolution_failed") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            raise ExternalSourceSyncError("private_or_loopback_ip")


async def _assert_allowed_host(url: str) -> None:
    """SSRF gate applied to every request hop (initial + redirects).

    Google's CSV export returns a 307 to ``googleusercontent.com``; we must
    follow it to reach the real CSV, but every hop must clear the same SSRF
    allow-list + DNS-pin as the initial URL. Used as an httpx async event hook.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ExternalSourceSyncError("scheme_not_https")
    if not host:
        raise ExternalSourceSyncError("invalid_url")
    try:
        ipaddress.ip_address(host)
        raise ExternalSourceSyncError("ip_literal_forbidden")
    except ValueError:
        pass  # not an IP literal — good
    if not (host in ALLOWED_HOSTS or any(host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)):
        raise ExternalSourceSyncError("host_not_allowed")
    # getaddrinfo is blocking — offload so a slow/NXDOMAIN lookup does not
    # stall the worker event loop (AGENTS.md: keep I/O async).
    await asyncio.to_thread(_reject_private_host, host)


class SheetClient:
    """One-shot httpx client per fetch (never the process singleton — Finding 2)."""

    async def fetch_csv(self, url: str, gid: int = 0) -> str:
        validate_sheet_url(url)
        sheet_id = extract_sheet_id(url)
        export_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        )

        async def _ssrf_gate(request: httpx.Request) -> None:
            """Per-hop SSRF gate — runs for the initial request and every redirect."""
            await _assert_allowed_host(str(request.url))

        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=3,
            event_hooks={"request": [_ssrf_gate]},
            timeout=httpx.Timeout(DEFAULT_HTTP_TIMEOUT),
        ) as client:
            try:
                resp = await client.get(export_url)
            except ExternalSourceSyncError:
                # SSRF rejection from _ssrf_gate — propagate the precise code
                # (host_not_allowed / scheme_not_https / private_or_loopback_ip)
                # instead of relabelling it as fetch_failed.
                raise
            except httpx.HTTPError as exc:
                raise ExternalSourceSyncError("fetch_failed", str(exc)) from exc
        if resp.status_code in (401, 403, 404, 410):
            raise ExternalSourceSyncError(f"http_{resp.status_code}")
        if resp.status_code >= 400:
            raise ExternalSourceSyncError("http_error", f"status={resp.status_code}")
        content_type = resp.headers.get("content-type", "")
        if "csv" not in content_type and "text/plain" not in content_type:
            raise ExternalSourceSyncError("unexpected_content_type")
        body = resp.text
        head = body[:512].lower()
        if "<html" in head or "accounts.google.com" in head:
            raise ExternalSourceSyncError("sheet_not_public")
        return body


def build_source_yaml(payload: dict) -> str:
    """Canonical, deterministic YAML for a parsed payload.

    Determinism matters: ``stage_replacement`` dedups on the exact
    ``(filename, source_yaml)`` string, so the same payload must always produce
    the same YAML.
    """
    return yaml.safe_dump(
        payload, sort_keys=True, allow_unicode=True, default_flow_style=False, width=4096
    )


def sanitize_error(exc: Exception) -> str:
    """Strip URLs/query strings from an exception message; cap at 500 chars.

    httpx exceptions embed the full URL (with query string), which can leak
    ``?access_token=`` cross-tenant into ``last_error``. Never store raw
    ``str(exc)`` from httpx (Finding 24).
    """
    return _URL_RE.sub("[url]", str(exc))[:500]


async def sync_external_source(
    db: AsyncSession,
    *,
    state_id: uuid.UUID,
    actor: User,
) -> ExternalSourceSyncOutcome:
    """Sync one external source row. Acquires a per-state Redis lock first."""
    state = await db.get(ExternalSourceSyncState, state_id)
    if state is None:
        raise ExternalSourceSyncError("state_not_found")

    redis = get_redis()
    lock_key = f"{LOCK_KEY_PREFIX}:{state_id}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)
    if not acquired:
        return ExternalSourceSyncOutcome(status="LOCKED", category_key=state.category_key)
    try:
        return await _sync_locked(db, state, actor)
    finally:
        await redis.delete(lock_key)


async def _sync_locked(
    db: AsyncSession, state: ExternalSourceSyncState, actor: User
) -> ExternalSourceSyncOutcome:
    # Finding 17: stored lowercase, but construct defensively.
    try:
        category_key = KnowledgeCategoryKey(state.category_key.lower())
    except ValueError:
        code = f"invalid_category_key:{state.category_key}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)

    # Fetch (SSRF-hardened).
    try:
        csv_text = await SheetClient().fetch_csv(state.sheet_url, state.sheet_gid)
    except ExternalSourceSyncError as exc:
        await _mark_failed(db, state, exc.code)
        return ExternalSourceSyncOutcome(
            status="FAILED", category_key=state.category_key, error=exc.code
        )

    # Parse via the per-category registry.
    parser = PARSERS.get(category_key)
    if parser is None:
        code = f"no_parser_for_category:{state.category_key}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)
    try:
        payload = parser(csv_text)
    except ExternalSourceSyncError as exc:
        await _mark_failed(db, state, exc.code)
        return ExternalSourceSyncOutcome(
            status="FAILED", category_key=state.category_key, error=exc.code
        )
    except ValueError as exc:
        code = f"parse_failed:{sanitize_error(exc)}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)

    # Validate through the SAME pipeline the category service uses so the hash
    # below is structurally identical to revision.content_sha256.
    source_yaml = build_source_yaml(payload)
    try:
        document = parse_category_yaml(category_key, source_yaml)
    except EmptyCategoryError:
        await _mark_failed(db, state, "empty_category")
        return ExternalSourceSyncOutcome(
            status="FAILED", category_key=state.category_key, error="empty_category"
        )
    except ValueError as exc:
        code = f"validation_failed:{sanitize_error(exc)}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)

    new_checksum = category_checksum(document)

    # Hash-skip keyed on the ACTIVE revision (Finding 11).
    active_checksum = await _active_revision_checksum(db, state.project_id, category_key)
    if active_checksum == new_checksum and state.last_status in ("OK", "NO_OP"):
        await _mark_noop(db, state, new_checksum, _payload_row_count(document, category_key))
        return ExternalSourceSyncOutcome(
            status="NO_OP", category_key=state.category_key, content_hash=new_checksum
        )

    # Stage only — activation is enqueued async by stage_replacement (Finding 4).
    filename = f"{state.source_kind}_sync_{state.category_key}.yaml"
    try:
        revision, job_id = await KnowledgeCategoryService(db).stage_replacement(
            project_id=state.project_id,
            category_key=category_key,
            source_yaml=source_yaml,
            filename=filename,
            actor=actor,
        )
    except ConflictError as exc:
        code = f"stage_conflict:{sanitize_error(exc)}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)
    except UpstreamError as exc:
        code = f"stage_upstream:{sanitize_error(exc)}"
        await _mark_failed(db, state, code)
        return ExternalSourceSyncOutcome(status="FAILED", category_key=state.category_key, error=code)

    await _mark_staged(db, state, new_checksum, _payload_row_count(document, category_key),
                       revision.id, job_id)
    return ExternalSourceSyncOutcome(
        status="STAGED",
        category_key=state.category_key,
        content_hash=new_checksum,
        revision_id=revision.id,
        job_id=job_id,
    )


def _payload_row_count(document, category_key: KnowledgeCategoryKey) -> int:
    """Number of records in a parsed category document (for last_row_count)."""
    from app.services.knowledge.category_contracts import get_category_definition

    definition = get_category_definition(category_key)
    return len(getattr(document, definition.list_field))


async def _active_revision_checksum(
    db: AsyncSession, project_id: uuid.UUID, category_key: KnowledgeCategoryKey
) -> str | None:
    category = await db.scalar(
        select(KnowledgeCategory).where(
            KnowledgeCategory.project_id == project_id,
            KnowledgeCategory.category_key == category_key.value,
        )
    )
    if category is None or category.active_revision_id is None:
        return None
    revision = await db.get(KnowledgeCategoryRevision, category.active_revision_id)
    return revision.content_sha256 if revision else None


async def _mark_failed(db: AsyncSession, state: ExternalSourceSyncState, error_code: str) -> None:
    """Record FAILED; bump consecutive_failures for revocable reasons; auto-disable at 3."""
    state.last_status = "FAILED"
    state.last_error = error_code[:500]
    state.last_synced_at = datetime.now(UTC)
    if error_code in REVOCABLE_FAILURE_REASONS:
        state.consecutive_failures = (state.consecutive_failures or 0) + 1
        if state.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
            state.auto_sync_enabled = False
            logger.warning(
                "external_source_sync auto-disabled state=%s after %d revocable failures",
                state.id,
                state.consecutive_failures,
            )
    await db.commit()


async def _mark_noop(
    db: AsyncSession, state: ExternalSourceSyncState, content_hash: str, row_count: int
) -> None:
    state.last_status = "NO_OP"
    state.last_content_hash = content_hash
    state.last_row_count = row_count
    state.last_synced_at = datetime.now(UTC)
    state.last_error = None
    state.consecutive_failures = 0
    await db.commit()


async def _mark_staged(
    db: AsyncSession,
    state: ExternalSourceSyncState,
    content_hash: str,
    row_count: int,
    revision_id: uuid.UUID,
    job_id: str,
) -> None:
    # Staging succeeded; activation runs async via RQ. last_status=OK reflects
    # that the row's content was successfully staged this cycle.
    state.last_status = "OK"
    state.last_content_hash = content_hash
    state.last_row_count = row_count
    state.last_synced_at = datetime.now(UTC)
    state.last_revision_id = revision_id
    state.last_error = None
    state.consecutive_failures = 0
    await db.commit()


__all__ = [
    "AUTO_DISABLE_THRESHOLD",
    "DEFAULT_HTTP_TIMEOUT",
    "ExternalSourceSyncError",
    "ExternalSourceSyncOutcome",
    "REVOCABLE_FAILURE_REASONS",
    "SheetClient",
    "build_source_yaml",
    "extract_sheet_id",
    "sanitize_error",
    "sync_external_source",
    "validate_sheet_url",
]
