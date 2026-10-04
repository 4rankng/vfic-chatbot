"""Scheduler tick: recover knowledge-ingest work orphaned by dead workers.

A deploy or crash kills ``worker-ingest``/``worker-category`` mid-job; RQ's
registries forget the job and nothing owns the in-flight document/revision
rows afterwards. ``reconcile_worker`` plays this role for chat turns; this
tick plays it for the knowledge pipeline via
``app.services.knowledge.recovery_sweep``.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

# Non-reentrancy guard, mirroring the reconcile tick.
_TICK_LOCK = "vfic:locks:knowledge-recovery-tick"
_TICK_LOCK_TTL_SECONDS = 600


def run_knowledge_recovery_tick() -> None:
    """Scheduler tick (sync entrypoint). Sweeps orphaned ingest artifacts."""
    from app.workers.async_runner import run_async

    run_async(_run_tick_async())


async def _run_tick_async() -> None:
    from app.core.redis import get_redis_sync

    conn = get_redis_sync()

    tick_owner = uuid.uuid4().hex
    if not conn.set(_TICK_LOCK, tick_owner, nx=True, ex=_TICK_LOCK_TTL_SECONDS):
        logger.debug("knowledge recovery tick: skipped — prior tick still running")
        return

    try:
        from app.services.knowledge.recovery_sweep import recover_abandoned_ingest_work
        from app.workers._db import worker_session

        async with worker_session() as db:
            counts = await recover_abandoned_ingest_work(db)
        if any(counts.values()):
            logger.warning("knowledge recovery sweep recovered: %s", counts)
    finally:
        # Prove ownership before deleting: a tick that overran into its
        # successor must not delete the successor's lock.
        if conn.get(_TICK_LOCK) == tick_owner:
            conn.delete(_TICK_LOCK)
