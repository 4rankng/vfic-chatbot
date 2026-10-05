"""Performance dashboard API — response time + phone-capture conversion.

Aggregates ``BotRun.stage_timings`` (captured by ``app.graph.runner.run_turn``)
into end-to-end p50/p95 plus a bucketed trend, and reads the candidate-phone
conversion rate over the same window. Admin-only.

Latency strategy (migration 0033 + concurrent reads + Redis cache):
- The three time-windowed reads (``_response_time_percentiles``, ``_trend``,
  ``_conversion``) run concurrently via ``asyncio.gather``, each on its own
  ``AsyncSession`` (a single session is not safe for concurrent use).
- The assembled payload is cached in Redis for 30 s (``_CACHE_TTL_SECONDS``),
  matching the frontend ``staleTime``. Auth always runs before the cache lookup.
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
    window: str = Query("7d", pattern="^(1d|7d|1m|3m|6m)$"),
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
