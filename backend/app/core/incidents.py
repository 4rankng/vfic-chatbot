"""Cross-process incident counters (Redis INCR), surfaced via ``/metrics``.

A WARNING-level swallow is the *designed* terminal state for best-effort
paths — realtime fan-out, post-commit bookkeeping, scheduler-tick armor.
These counters are what makes that terminal state visible to operators
instead of discoverable only by grepping container logs: every catch that
downgrades an exception to a warning increments a monotonically rising key,
``/metrics`` exports it, and ``scripts/ops-alerts.sh`` polls it.

Uses the SYNC Redis client everywhere, matching the existing worker-side
counter writes (``reconcile_worker``, ``knowledge_recovery_worker``): the
increment fires on an already-degraded path, where one sub-millisecond
``INCR`` is noise. Counting must never raise — an observability failure
cannot be allowed to break the path it observes.
"""

from __future__ import annotations

import logging

from app.core.redis import get_redis_sync

logger = logging.getLogger(__name__)

# Realtime payload could not be built (ORM relationship lazy-loaded outside
# the async greenlet, or serialization raised) — the recruiter UI misses an
# update. Only ever rises; investigate on first sighting.
REALTIME_PAYLOAD_FAILURES = "realtime_payload_failures_total"
# The Socket.IO/Redis publish of an already-built payload failed.
REALTIME_PUBLISH_FAILURES = "realtime_publish_failures_total"
# The knowledge recovery tick raised — orphaned ingest work is NOT being
# recovered while this rises (RQ also records the failed job).
KNOWLEDGE_RECOVERY_FAILURES = "knowledge_recovery_failures_total"

ALL_COUNTERS = (
    REALTIME_PAYLOAD_FAILURES,
    REALTIME_PUBLISH_FAILURES,
    KNOWLEDGE_RECOVERY_FAILURES,
)


def count_incident(key: str) -> None:
    """INCR an incident counter. Never raises, never blocks the caller's flow."""
    try:
        get_redis_sync().incr(key)
    except Exception:  # noqa: BLE001 — observability must not break the observed path
        logger.debug("incident counter incr failed key=%s", key, exc_info=True)
