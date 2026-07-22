"""RQ entry points for single-page external-source sync."""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 86400
DEFAULT_JOB_TIMEOUT_SECONDS = 1800
DEFAULT_RETRY_MAX = 3
DEFAULT_RETRY_INTERVALS_SECONDS = [60, 300, 900]
COUNTER_SUCCESS = "single_page_external_source_sync_success_total"
COUNTER_FAILURE = "single_page_external_source_sync_failure_total"
COUNTER_TTL_SECONDS = 7 * 24 * 3600


def run_single_page_external_source_sync_tick() -> None:
    from app.workers.async_runner import run_async

    run_async(_tick_async())


async def _tick_async() -> None:
    from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
    from app.workers._db import worker_session

    today = date.today().isoformat()
    async with worker_session() as db:
        rows = (
            (
                await db.execute(
                    select(SinglePageExternalSourceSyncState.id).where(
                        SinglePageExternalSourceSyncState.auto_sync_enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    queued = 0
    for state_id in rows:
        if enqueue_one_shot(
            state_id, job_id=f"single-page-ext-src-sync-{state_id}-{today}"
        ):
            queued += 1
    logger.info(
        "single_page_external_source_sync tick enqueued=%d of %d auto-sync rows",
        queued,
        len(rows),
    )


def run_single_page_external_source_sync_job(state_id: str) -> None:
    from app.workers.async_runner import run_async

    run_async(_run_job_async(uuid.UUID(state_id)))


async def _run_job_async(state_id: uuid.UUID) -> None:
    from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
    from app.services.knowledge.external_source_sync import ExternalSourceSyncError
    from app.services.project.single_page_external_sources import sync_single_page_external_source
    from app.workers._db import worker_session

    async with worker_session() as db:
        state = await db.get(SinglePageExternalSourceSyncState, state_id)
        if state is None:
            logger.warning("single_page_external_source_sync job: state %s not found", state_id)
            return
        try:
            actor = await _resolve_actor(db, state)
            outcome = await sync_single_page_external_source(db, state_id=state_id, actor=actor)
        except ExternalSourceSyncError as exc:
            logger.warning(
                "single_page_external_source_sync failed state=%s code=%s", state_id, exc.code
            )
            _bump_counter(COUNTER_FAILURE)
            return

        if outcome.status == "OK":
            _bump_counter(COUNTER_SUCCESS)
            logger.info(
                "single_page_external_source_sync state=%s status=OK hash=%s rows=%s",
                state_id,
                (outcome.content_hash or "")[:8],
                outcome.row_count,
            )
        elif outcome.status == "NO_OP":
            _bump_counter(COUNTER_SUCCESS)
            logger.info(
                "single_page_external_source_sync state=%s status=NO_OP", state_id
            )
        elif outcome.status == "FAILED":
            _bump_counter(COUNTER_FAILURE)
            logger.warning(
                "single_page_external_source_sync state=%s status=FAILED error=%s",
                state_id,
                outcome.error,
            )
        else:
            logger.info("single_page_external_source_sync state=%s status=LOCKED", state_id)


def enqueue_one_shot(state_id: uuid.UUID, *, job_id: str | None = None) -> str | None:
    from rq import Retry

    from app.workers.utils import enqueue_job

    return enqueue_job(
        "ingest",
        run_single_page_external_source_sync_job,
        str(state_id),
        job_timeout=DEFAULT_JOB_TIMEOUT_SECONDS,
        retry=Retry(max=DEFAULT_RETRY_MAX, interval=DEFAULT_RETRY_INTERVALS_SECONDS),
        return_job_id=True,
        job_id=job_id,
    )


async def _resolve_actor(db, state):
    from app.models.user import Role, User
    from app.services.knowledge.external_source_sync import ExternalSourceSyncError

    if state.created_by is not None:
        user = await db.get(User, state.created_by)
        if user is not None and user.role is Role.admin and not user.disabled:
            return user
    admin = await db.scalar(
        select(User)
        .where(User.role == Role.admin, User.disabled.is_(False))
        .order_by(User.created_at)
    )
    if admin is None:
        raise ExternalSourceSyncError("no_sync_actor")
    logger.warning(
        "single_page_external_source_sync state=%s falling back to admin=%s (created_by=%s unresolved)",
        getattr(state, "id", None),
        admin.id,
        state.created_by,
    )
    return admin


def _bump_counter(key: str) -> None:
    try:
        from app.core.redis import get_redis_sync

        client = get_redis_sync()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, COUNTER_TTL_SECONDS)
        pipe.execute()
    except Exception:  # noqa: BLE001
        logger.debug("single_page_external_source_sync counter bump failed", exc_info=True)
