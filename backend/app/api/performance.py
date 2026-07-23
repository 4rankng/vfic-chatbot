"""Performance dashboard API — per-stage turn-latency metrics for the Hiệu suất panel.

Aggregates ``BotRun.stage_timings`` (captured by ``app.graph.runner.run_turn``) into
p50/p95/p99 per stage, plus by-lane/outcome counts and the slowest recent turns.
Live tiles reuse the ``/health/queue`` snapshot via ``collect_queue_health``. Admin-only.

Latency strategy (migration 0033 + concurrent reads + Redis cache):
- The five time-windowed reads (``_percentiles``, ``_lane_outcome_counts``,
  ``_slow_turns``, ``_trend``, ``_reliability``) run concurrently via
  ``asyncio.gather``, each on its own ``AsyncSession`` (a single session is not
  safe for concurrent use). Pool ``pool_size=10`` has ample headroom for 5 reads.
- The assembled payload is cached in Redis for 30 s (``_CACHE_TTL_SECONDS``),
  matching the frontend ``staleTime``. Auth always runs before the cache lookup.
- Cache tradeoff: on a hit, the ``live`` tile (queue depth / worker saturation)
  is served from the 30 s-old snapshot rather than re-read from Redis. This is
  acceptable for an admin trends view and matches the frontend's existing
  ``staleTime: 30s`` treatment of the whole payload.
"""

from fastapi import APIRouter, Depends, Query

from app.api.auth_dependencies import require_admin
from app.identity.application.http import AuthenticatedUser
from app.reporting.infrastructure.performance_dashboard import (
    performance_dashboard,
    performance_slos_dashboard,
)

router = APIRouter(prefix="/admin/performance", tags=["performance"])


@router.get("")
async def performance(
    window: str = Query("24h", pattern="^(1h|24h|7d)$"),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    return await performance_dashboard(window)


@router.get("/slos")
async def performance_slos(
    window: str = Query("24h", pattern="^(1h|24h|7d)$"),
    _admin: AuthenticatedUser = Depends(require_admin),
) -> dict:
    """Latency + reliability SLOs (Tech-Lead Directive §1).

    Returns the 7 named SLOs with target + actual p50/p95 + green/amber/red
    status. SLO computation reuses ``BotRun.stage_timings`` via
    ``app.services.slo_service.compute_slos``; the ``webhook_ack`` SLO reads
    from a Redis sliding window sampled at webhook ack time (no BotRun row
    exists that early). Cached 30 s to match the main dashboard.
    """
    return await performance_slos_dashboard(window)
