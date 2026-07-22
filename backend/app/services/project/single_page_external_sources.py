"""Single-page external-source CRUD + sync orchestration."""

from __future__ import annotations

import logging
import re
import csv
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.core.redis import get_redis
from app.models.company import Project
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
from app.models.user import User
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.schemas.project_single_page_sync import SinglePageExternalSourceCreate
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError, UpstreamError
from app.services.knowledge.external_source_sync import (
    AUTO_DISABLE_THRESHOLD,
    LOCK_TTL_SECONDS,
    REVOCABLE_FAILURE_REASONS,
    ExternalSourceSyncError,
    SheetClient,
    extract_sheet_id,
    validate_sheet_url,
)
from app.services.knowledge.external_source_sync.parsers import parse_faq_csv
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.project.repository import require_project

logger = logging.getLogger(__name__)

SOURCE_KIND_GOOGLE_SHEET = "google_sheet"
RUN_NOW_COOLDOWN_SECONDS = 300
LOCK_KEY_PREFIX = "single_page_ext_src_sync"
SINGLE_PAGE_LOCK_TTL_SECONDS = 1900
SINGLE_PAGE_SHEET_MAX_BYTES = 300_000
SYNC_FILENAME = "single-page-google-sheet-sync.md"
_SAFE_JS_INTEGER_MAX = 9_007_199_254_740_991
_DECIMAL_RE = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class SinglePageExternalSourceSyncOutcome:
    """Result of one single-page sync attempt."""

    status: str
    content_hash: str | None = None
    row_count: int | None = None
    error: str | None = None
    job_id: str | None = None


def parse_sheet_gid(url: str) -> int:
    """Extract exactly one coherent gid from a user-pasted Google Sheets URL.

    Google places the selected tab in the fragment (``#gid=...``) on normal
    edit/view URLs, but export-style links may carry it in the query string.
    Fragment wins when both exist so the backend mirrors what the user selected
    in the browser before copying the URL.
    """
    parsed = urllib.parse.urlparse(url)
    fragment_pairs = urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    source_pairs = fragment_pairs if any(key == "gid" for key, _ in fragment_pairs) else query_pairs
    raw_values = [value for key, value in source_pairs if key == "gid"]
    if not raw_values:
        raise ExternalSourceSyncError("missing_gid")

    normalized_values: set[int] = set()
    for raw_value in raw_values:
        if not _DECIMAL_RE.fullmatch(raw_value):
            raise ExternalSourceSyncError("invalid_gid")
        gid = int(raw_value)
        if gid > _SAFE_JS_INTEGER_MAX:
            raise ExternalSourceSyncError("unsafe_gid")
        normalized_values.add(gid)
    if len(normalized_values) != 1:
        raise ExternalSourceSyncError("conflicting_gid")
    return normalized_values.pop()


def render_sheet_markdown(csv_text: str) -> tuple[str, int]:
    """Deterministically render the FAQ sheet into markdown for DIRECT_CONTEXT."""
    payload = parse_faq_csv(csv_text)
    items = payload.get("faq") or []
    if not items:
        raise ExternalSourceSyncError("empty_sheet")

    lines = ["# Câu hỏi thường gặp", "", "## FAQ", ""]
    for item in items:
        question = str(item["question"]).strip()
        answer = str(item["answer"]).strip()
        tags = [str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()]
        lines.append(f"### FAQ: {question}")
        lines.append("")
        lines.append(f"Question: {question}")
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")
        lines.append("")
        lines.append("Answer:")
        lines.append(answer)
        lines.append("")
    return "\n".join(lines).strip() + "\n", len(items)


class SinglePageExternalSourceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_sources(
        self, project_id: uuid.UUID
    ) -> list[SinglePageExternalSourceSyncState]:
        await self._require_direct_context_project(project_id)
        rows = (
            (
                await self.db.execute(
                    select(SinglePageExternalSourceSyncState)
                    .where(SinglePageExternalSourceSyncState.project_id == project_id)
                    .order_by(SinglePageExternalSourceSyncState.created_at)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def create_source(
        self,
        project_id: uuid.UUID,
        body: SinglePageExternalSourceCreate,
        actor: User,
    ) -> SinglePageExternalSourceSyncState:
        await self._require_direct_context_project(project_id)
        try:
            validate_sheet_url(body.sheet_url)
            extract_sheet_id(body.sheet_url)
            sheet_gid = parse_sheet_gid(body.sheet_url)
        except ExternalSourceSyncError as exc:
            raise ConflictError(exc.code) from exc

        row = SinglePageExternalSourceSyncState(
            project_id=project_id,
            source_kind=SOURCE_KIND_GOOGLE_SHEET,
            sheet_url=body.sheet_url.strip(),
            sheet_gid=sheet_gid,
            auto_sync_enabled=body.auto_sync_enabled,
            consecutive_failures=0,
            last_status="NEW",
            created_by=actor.id,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("single_page_external_source_already_exists") from exc
        await record_audit(
            self.db,
            action="single_page_external_source_created",
            actor_id=actor.id,
            target_type="single_page_external_source_sync_state",
            target_id=str(row.id),
            payload={"project_id": str(project_id), "sheet_gid": row.sheet_gid},
        )
        await self.db.commit()
        await self.db.refresh(row)

        from app.workers.single_page_external_source_sync_worker import enqueue_one_shot

        from app.workers.utils import EnqueueStatusUnknown

        try:
            job_id = enqueue_one_shot(row.id)
        except EnqueueStatusUnknown:
            logger.warning(
                "single_page_external_source create enqueue receipt unknown row=%s code=%s",
                row.id,
                "enqueue_status_unknown",
            )
            return row
        if job_id is None:
            logger.warning(
                "single_page_external_source create enqueue failed; removing NEW row=%s code=%s",
                row.id,
                "enqueue_failed",
            )
            await self.db.delete(row)
            await self.db.commit()
            raise UpstreamError("single_page_sync_enqueue_failed")
        return row

    async def run_now(self, project_id: uuid.UUID, source_id: uuid.UUID, actor: User) -> str:
        row = await self._load_source(project_id, source_id)
        redis = get_redis()
        cooldown_key = f"single-page-ext-src-run-now:{source_id}"
        acquired = await redis.set(cooldown_key, "1", nx=True, ex=RUN_NOW_COOLDOWN_SECONDS)
        if not acquired:
            raise ConflictError("run_now_cooldown")

        from app.workers.single_page_external_source_sync_worker import enqueue_one_shot

        from app.workers.utils import EnqueueStatusUnknown

        requested_job_id = f"single-page-ext-src-sync-{source_id}-{uuid.uuid4().hex}"
        try:
            job_id = enqueue_one_shot(row.id, job_id=requested_job_id)
        except EnqueueStatusUnknown as exc:
            # The job may already be accepted. Keep the cooldown so a retry
            # cannot submit a duplicate while the queue receipt is uncertain.
            logger.warning(
                "single_page_external_source run-now enqueue receipt unknown state=%s code=%s",
                row.id,
                "enqueue_status_unknown",
            )
            raise UpstreamError("single_page_sync_enqueue_status_unknown") from exc
        if job_id is None:
            await redis.delete(cooldown_key)
            raise UpstreamError("single_page_sync_enqueue_failed")
        await record_audit(
            self.db,
            action="single_page_external_source_run_now",
            actor_id=actor.id,
            target_type="single_page_external_source_sync_state",
            target_id=str(source_id),
            payload={"project_id": str(project_id), "job_id": job_id},
        )
        await self.db.commit()
        return job_id

    async def delete_source(self, project_id: uuid.UUID, source_id: uuid.UUID, actor: User) -> None:
        row = await self._load_source(project_id, source_id)
        await self.db.delete(row)
        await record_audit(
            self.db,
            action="single_page_external_source_deleted",
            actor_id=actor.id,
            target_type="single_page_external_source_sync_state",
            target_id=str(source_id),
            payload={"project_id": str(project_id), "sheet_gid": row.sheet_gid},
        )
        await self.db.commit()

    async def _load_source(
        self, project_id: uuid.UUID, source_id: uuid.UUID
    ) -> SinglePageExternalSourceSyncState:
        await self._require_direct_context_project(project_id)
        row = await self.db.get(SinglePageExternalSourceSyncState, source_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("single_page_external_source_not_found")
        return row

    async def _require_direct_context_project(
        self, project_id: uuid.UUID
    ) -> tuple[Project, KnowledgeBase]:
        project = await require_project(self.db, project_id)
        knowledge_base = (
            await self.db.get(KnowledgeBase, project.knowledge_base_id)
            if project.knowledge_base_id
            else None
        )
        if knowledge_base is None or knowledge_base.mode is not KnowledgeBaseMode.DIRECT_CONTEXT:
            raise ConflictError("This operation requires a single-page Project")
        return project, knowledge_base


async def sync_single_page_external_source(
    db: AsyncSession,
    *,
    state_id: uuid.UUID,
    actor: User,
) -> SinglePageExternalSourceSyncOutcome:
    """Sync one single-page external source row under a Redis lock."""
    state = await db.get(SinglePageExternalSourceSyncState, state_id)
    if state is None:
        raise ExternalSourceSyncError("state_not_found")

    redis = get_redis()
    lock_key = f"{LOCK_KEY_PREFIX}:{state_id}"
    lock_owner = uuid.uuid4().hex
    acquired = await redis.set(
        lock_key,
        lock_owner,
        nx=True,
        ex=min(LOCK_TTL_SECONDS, SINGLE_PAGE_LOCK_TTL_SECONDS),
    )
    if not acquired:
        return SinglePageExternalSourceSyncOutcome(status="LOCKED")
    try:
        return await _sync_locked(db, state, actor)
    finally:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            lock_owner,
        )


async def _sync_locked(
    db: AsyncSession,
    state: SinglePageExternalSourceSyncState,
    actor: User,
) -> SinglePageExternalSourceSyncOutcome:
    try:
        project, knowledge_base = await SinglePageExternalSourceService(
            db
        )._require_direct_context_project(state.project_id)
    except (NotFoundError, ConflictError):
        code = "project_invalid"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)

    activating = not project.is_active
    if activating and not project.index_card:
        code = "project_invalid:single_page_needs_discovery_card"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)

    try:
        csv_text = await SheetClient().fetch_csv(
            state.sheet_url,
            state.sheet_gid,
            max_bytes=SINGLE_PAGE_SHEET_MAX_BYTES,
        )
        markdown, row_count = render_sheet_markdown(csv_text)
    except ExternalSourceSyncError as exc:
        await _mark_failed(db, state, exc.code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=exc.code)
    except csv.Error:
        code = "parse_failed:csv_field_too_large"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)
    except ValueError:
        code = "sheet_parse_failed"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)

    try:
        body = DirectContextFileUpsert(filename=SYNC_FILENAME, text=markdown)
    except ValidationError:
        code = "direct_file_rejected:content_too_large"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)
    stats = KnowledgeBaseService.canonical_direct_file_stats(body.text)
    current_file = await db.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    if current_file is not None and current_file.content_sha256 == stats.content_sha256:
        if activating:
            await _stage_project_activation(db, project, actor)
        await _mark_noop(db, state, stats.content_sha256, row_count)
        if activating:
            await bump_cache_version(NS_PREAMBLE)
        return SinglePageExternalSourceSyncOutcome(
            status="NO_OP", content_hash=stats.content_sha256, row_count=row_count
        )

    try:
        async with db.begin_nested():
            await KnowledgeBaseService(db).upsert_direct_file(
                knowledge_base.id,
                body,
                actor,
                commit=False,
            )
            if activating:
                await _stage_project_activation(db, project, actor)
    except ConflictError:
        code = "direct_file_rejected"
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)
    except Exception as exc:  # noqa: BLE001 - preserve the prior page on any caught failure
        code = "direct_file_update_failed"
        logger.warning(
            "single_page_external_source direct-file update failed state=%s code=%s error_type=%s",
            state.id,
            code,
            type(exc).__name__,
        )
        await _mark_failed(db, state, code)
        return SinglePageExternalSourceSyncOutcome(status="FAILED", error=code)

    await _mark_ok(db, state, stats.content_sha256, row_count)
    if activating:
        await bump_cache_version(NS_PREAMBLE)
    return SinglePageExternalSourceSyncOutcome(
        status="OK",
        content_hash=stats.content_sha256,
        row_count=row_count,
    )


async def _stage_project_activation(db: AsyncSession, project: Project, actor: User) -> None:
    project.is_active = True
    await record_audit(
        db,
        action="update_project",
        actor_id=actor.id,
        target_type="project",
        target_id=str(project.id),
        payload={"is_active": True, "reason": "single_page_ready"},
    )


async def _mark_failed(
    db: AsyncSession,
    state: SinglePageExternalSourceSyncState,
    error_code: str,
) -> None:
    state.last_status = "FAILED"
    state.last_error = error_code[:500]
    state.last_synced_at = datetime.now(UTC)
    if error_code in REVOCABLE_FAILURE_REASONS:
        state.consecutive_failures = (state.consecutive_failures or 0) + 1
        if state.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
            state.auto_sync_enabled = False
            logger.warning(
                "single_page_external_source auto-disabled state=%s after %d revocable failures",
                state.id,
                state.consecutive_failures,
            )
    await db.commit()


async def _mark_noop(
    db: AsyncSession,
    state: SinglePageExternalSourceSyncState,
    content_hash: str,
    row_count: int,
) -> None:
    state.last_status = "NO_OP"
    state.last_content_hash = content_hash
    state.last_row_count = row_count
    state.last_synced_at = datetime.now(UTC)
    state.last_error = None
    state.consecutive_failures = 0
    await db.commit()


async def _mark_ok(
    db: AsyncSession,
    state: SinglePageExternalSourceSyncState,
    content_hash: str,
    row_count: int,
) -> None:
    state.last_status = "OK"
    state.last_content_hash = content_hash
    state.last_row_count = row_count
    state.last_synced_at = datetime.now(UTC)
    state.last_error = None
    state.consecutive_failures = 0
    await db.commit()


__all__ = [
    "RUN_NOW_COOLDOWN_SECONDS",
    "SOURCE_KIND_GOOGLE_SHEET",
    "SINGLE_PAGE_SHEET_MAX_BYTES",
    "SinglePageExternalSourceService",
    "SinglePageExternalSourceSyncOutcome",
    "parse_sheet_gid",
    "render_sheet_markdown",
    "sync_single_page_external_source",
]
