"""Dashboard metrics: open conversations, hot leads, pending follow-ups, bot
suppression rate, failed sends, bot errors. Scoped to the viewer (admin = global,
recruiter = assigned)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.models.user import Role, User
from app.schemas.job import DashboardMetrics, KnowledgeIngestHealth
from app.services.dashboard.repository import DashboardRepository

# Canonical recruitment-funnel order (mirrors the leads.lead_stage CHECK
# constraint + the frontend LEAD_STAGES list). Used to emit stage_breakdown in a
# stable order including zero-count stages, so the client never has to sort.
_LEAD_STAGE_ORDER = (
    "NEW",
    "CONTACTING",
    "REGISTERED",
    "SKIPPED",
)

logger = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def metrics(self, viewer: User) -> DashboardMetrics:
        settings = get_settings()
        cache_enabled = settings.dashboard_cache_enabled and settings.app_env == "production"
        cache_scope = "admin" if viewer.role == Role.admin else f"recruiter:{viewer.id}"
        cache_key = f"dashboard:metrics:{cache_scope}"
        if cache_enabled:
            cached = await cache_get_json(cache_key)
            if isinstance(cached, dict):
                return DashboardMetrics.model_validate(cached)

        # Every count is scoped to the viewer: admin = global, recruiter = assigned
        # to them or unassigned. The repo takes ``recruiter_id=None`` for global.
        recruiter_id = None if viewer.role == Role.admin else str(viewer.id)
        repo = DashboardRepository(self.db)
        open_convs = await repo.count_open_conversations(recruiter_id)
        hot_leads = await repo.count_hot_leads(recruiter_id)
        pending_fu = await repo.count_pending_followups(recruiter_id)
        failed_sends = await repo.count_failed_sends(recruiter_id)
        bot_errors = await repo.count_bot_errors(recruiter_id)
        suppression = await repo.bot_suppression_rate(recruiter_id)
        bot_summary = await repo.bot_run_summary(recruiter_id)
        counts_by_stage = await repo.leads_by_stage(recruiter_id)
        human_convs = await repo.count_human_conversations(recruiter_id)

        # Concurrent-load monitoring (chatbot readiness)
        queue_depth = self._webhook_queue_depth()
        active_turns_count = await repo.active_turns()
        p95_latency = await repo.bot_run_p95_latency()
        recent_turns = await repo.recent_turns_count(5)

        total_leads = sum(counts_by_stage.values())
        registered_count = counts_by_stage.get("REGISTERED", 0)
        qualified_count = 0  # no distinct QUALIFIED stage in the 4-stage model
        hired_count = registered_count  # REGISTERED is the closest funnel endpoint
        bot_run_count = int(bot_summary["total"] or 0)
        bot_sent_count = int(bot_summary["sent"] or 0)
        stage_breakdown = [
            {
                "value": stage,
                "count": counts_by_stage.get(stage, 0),
                "percentage": round(counts_by_stage.get(stage, 0) / total_leads * 100)
                if total_leads
                else 0,
            }
            for stage in _LEAD_STAGE_ORDER
        ]

        metrics = DashboardMetrics(
            open_conversations=int(open_convs or 0),
            hot_leads=int(hot_leads or 0),
            pending_followups=int(pending_fu or 0),
            bot_suppression_rate=float(suppression or 0.0),
            failed_zalo_sends=int(failed_sends or 0),
            bot_errors=int(bot_errors or 0),
            bot_run_count=bot_run_count,
            bot_sent_count=bot_sent_count,
            bot_suppressed_count=int(bot_summary["suppressed"] or 0),
            bot_success_rate=round(bot_sent_count / bot_run_count * 100) if bot_run_count else 0.0,
            avg_bot_response_seconds=round(float(bot_summary["avg_seconds"] or 0.0), 1),
            total_leads=total_leads,
            qualified_count=qualified_count,
            hired_count=hired_count,
            hired_rate=round(hired_count / total_leads * 100) if total_leads else 0.0,
            unread_conversation_count=int(human_convs or 0),
            stage_breakdown=stage_breakdown,
            knowledge_ingest=await self._knowledge_ingest_health() if viewer.role == Role.admin else None,
            webhook_queue_depth=queue_depth,
            active_turns=active_turns_count,
            p95_bot_response_seconds=round(float(p95_latency), 1),
            turns_last_5min=recent_turns,
        )
        if cache_enabled:
            await cache_set_json(
                cache_key, metrics.model_dump(mode="json"), settings.dashboard_cache_ttl_seconds
            )
        return metrics

    async def _knowledge_ingest_health(self) -> KnowledgeIngestHealth:
        """Admin-only health snapshot for the async knowledge ingest pipeline."""
        repo = DashboardRepository(self.db)
        counts = await repo.knowledge_stage_counts()
        processing_stages = ("UPLOADED", "EXTRACTED", "DIGESTING", "EMBEDDING", "INDEXING", "PROCESSING")
        processing_count = sum(counts.get(stage, 0) for stage in processing_stages)
        stuck_count = int(await repo.count_stuck_documents(list(processing_stages)) or 0)
        issue_rows = await repo.recent_ingest_issues(list(processing_stages))
        queue_depth, failed_job_count, worker_count = self._rq_ingest_counts()
        return KnowledgeIngestHealth(
            queue_depth=queue_depth,
            failed_job_count=failed_job_count,
            worker_count=worker_count,
            processing_count=processing_count,
            stuck_count=stuck_count,
            failed_document_count=counts.get("FAILED", 0),
            published_document_count=counts.get("PUBLISHED", 0),
            stage_breakdown=[{"stage": stage, "count": count} for stage, count in counts.items()],
            recent_issues=[
                {
                    "id": row["id"],
                    "file_name": row["file_name"],
                    "project_id": row["project_id"],
                    "status": row["status"],
                    "stage": row["stage"],
                    "minutes_since_update": int(row["minutes_since_update"] or 0),
                    "error": row["error"] or None,
                }
                for row in issue_rows
            ],
        )

    def _webhook_queue_depth(self) -> int:
        """Current depth of the webhook_high RQ queue (messages waiting for a worker slot)."""
        try:
            from rq import Queue

            from app.core.redis import get_redis_sync

            return Queue("webhook_high", connection=get_redis_sync()).count
        except Exception:  # noqa: BLE001 — Redis telemetry must not break dashboard
            logger.warning("failed to read webhook_high queue depth", exc_info=True)
            return 0

    def _rq_ingest_counts(self) -> tuple[int, int, int]:
        try:
            from app.core.redis import get_redis_sync

            redis = get_redis_sync()
            queue_depth = int(redis.llen("rq:queue:ingest") or 0)
            failed_job_count = int(redis.zcard("rq:failed:ingest") or 0)
            worker_count = int(redis.scard("rq:workers:ingest") or 0)
            return queue_depth, failed_job_count, worker_count
        except Exception:  # noqa: BLE001 — Redis telemetry must not break dashboard
            return 0, 0, 0
