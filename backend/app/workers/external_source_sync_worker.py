"""RQ entry points for external knowledge-source sync.

The daily tick (registered in ``app.main`` lifespan, runs in the ``scheduler``
container) enqueues one job per ``auto_sync_enabled`` row onto the ``ingest``
queue; ``worker-ingest`` runs ``run_external_source_sync_job``. Mirrors the
outbound-dispatch tick pattern: sync entrypoint → ``run_async`` → ``worker_session``
(Finding 21: worker pool, not the web pool).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Module-level operational constants. Daily re-ingest cadence is pinned to a
# wall-clock time via settings.kb_sync_cron (see app.main lifespan) so a
# web-container restart mid-day no longer pushes the next sync out by 24h.
DEFAULT_JOB_TIMEOUT_SECONDS = 1800  # 30 min RQ cap — embedder is serialized

COUNTER_SUCCESS = "external_source_sync_success_total"
COUNTER_FAILURE = "external_source_sync_failure_total"
COUNTER_TTL_SECONDS = 7 * 24 * 3600


def run_external_source_sync_tick() -> None:
    """rq-scheduler entry: enqueue one sync job per auto-sync-enabled row.

    Job ids are daily-dedupe (``ext-src-sync-{state_id}-{YYYY-MM-DD}``) so a tick
    that fires twice in one day is a no-op the second time. The run-now API path
    uses unique-per-click ids instead (Finding 9).
    """
    from app.workers.async_runner import run_async

    run_async(_tick_async())


async def _tick_async() -> None:
    from app.models.external_source_sync_state import ExternalSourceSyncState
    from app.workers._db import worker_session

    today = date.today().isoformat()
    async with worker_session() as db:
        rows = (
            (await db.execute(
                select(ExternalSourceSyncState.id).where(
                    ExternalSourceSyncState.auto_sync_enabled.is_(True)
                )
            ))
            .scalars()
            .all()
        )

    queued = 0
    for state_id in rows:
        if enqueue_one_shot(state_id, job_id=f"ext-src-sync-{state_id}-{today}"):
            queued += 1
    logger.info(
        "external_source_sync tick enqueued=%d of %d auto-sync rows", queued, len(rows)
    )


def run_external_source_sync_job(state_id: str) -> None:
    """RQ job entrypoint (sync). Runs one sync on the worker event loop."""
    from app.workers.async_runner import run_async

    run_async(_run_job_async(uuid.UUID(state_id)))


async def _run_job_async(state_id: uuid.UUID) -> None:
    from app.models.external_source_sync_state import ExternalSourceSyncState
    from app.services.knowledge.external_source_sync import (
        ExternalSourceSyncError,
        sync_external_source,
    )
    from app.workers._db import worker_session

    async with worker_session() as db:
        state = await db.get(ExternalSourceSyncState, state_id)
        if state is None:
            logger.warning("external_source_sync job: state %s not found", state_id)
            return
        try:
            actor = await _resolve_actor(db, state)
            outcome = await sync_external_source(db, state_id=state_id, actor=actor)
        except ExternalSourceSyncError as exc:
            logger.warning("external_source_sync failed state=%s code=%s", state_id, exc.code)
            _bump_counter(COUNTER_FAILURE)
            return

        if outcome.status == "STAGED":
            _bump_counter(COUNTER_SUCCESS)
            logger.info(
                "external_source_sync state=%s category=%s status=STAGED hash=%s revision=%s",
                state_id,
                outcome.category_key,
                (outcome.content_hash or "")[:8],
                outcome.revision_id,
            )
        elif outcome.status == "NO_OP":
            _bump_counter(COUNTER_SUCCESS)
            logger.info(
                "external_source_sync state=%s category=%s status=NO_OP (unchanged)",
                state_id,
                outcome.category_key,
            )
        elif outcome.status == "FAILED":
            _bump_counter(COUNTER_FAILURE)
            logger.warning(
                "external_source_sync state=%s status=FAILED error=%s",
                state_id,
                outcome.error,
            )
        else:  # LOCKED — a concurrent run-now/daily tick holds the per-state lock
            logger.info("external_source_sync state=%s status=LOCKED (skipped)", state_id)


def enqueue_one_shot(state_id: uuid.UUID, *, job_id: str | None = None) -> str | None:
    """Enqueue a single sync job. Shared by the daily tick and the API paths.

    ``job_id`` controls dedupe: the daily tick passes a daily-dedupe id; run-now
    passes a unique-per-click id so an admin retry within the same day actually
    runs (Finding 9).
    """
    from app.workers.utils import enqueue_job

    return enqueue_job(
        "ingest",
        run_external_source_sync_job,
        str(state_id),
        job_timeout=DEFAULT_JOB_TIMEOUT_SECONDS,
        return_job_id=True,
        job_id=job_id,
    )


async def _resolve_actor(db, state):
    """Resolve the User to attribute the staged revision to.

    Prefers the admin who configured the link (``state.created_by``); falls back
    to any admin so a background tick always has a valid actor.
    """
    from app.models.user import Role, User
    from app.services.knowledge.external_source_sync import ExternalSourceSyncError

    if state.created_by is not None:
        user = await db.get(User, state.created_by)
        if user is not None:
            return user
    admin = await db.scalar(
        select(User).where(User.role == Role.admin).order_by(User.created_at)
    )
    if admin is None:
        raise ExternalSourceSyncError("no_sync_actor")
    # Fallback attribution: created_by is null or gone (legacy/seeded row, or the
    # admin was deleted). Prefer this over failing the tick (a stale FAQ is worse
    # than a misattributed audit row), but surface it so ops can investigate.
    logger.warning(
        "external_source_sync state=%s falling back to admin=%s (created_by=%s unresolved)",
        getattr(state, "id", None),
        admin.id,
        state.created_by,
    )
    return admin


def _bump_counter(key: str) -> None:
    """Best-effort Redis counter bump with a 7-day TTL (dashboard observability)."""
    try:
        from app.core.redis import get_redis_sync

        client = get_redis_sync()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, COUNTER_TTL_SECONDS)
        pipe.execute()
    except Exception:  # noqa: BLE001 — counters are best-effort observability
        logger.debug("external_source_sync counter bump failed", exc_info=True)
