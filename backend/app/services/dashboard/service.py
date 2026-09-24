"""Dashboard metrics: open conversations, hot leads, pending follow-ups, bot
suppression rate, failed sends, bot errors. Scoped to the viewer (admin = global,
recruiter = assigned).

Bot-run aggregates (bot_run_count, bot_sent_count, bot_suppressed_count,
bot_success_rate, bot_suppression_rate, avg_bot_response_seconds) cover the
LAST 24 HOURS, not all-time: the ``bot_runs`` audit table is never pruned, so
unbounded aggregates grow linearly forever. Lead, conversation, follow-up,
and the bot_errors counters are current-state, not windowed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.models.user import Role, User
from app.schemas.dashboard import (
    AttentionAction,
    AttentionCounters,
    AttentionDashboardOut,
    AttentionItemOut,
    AttentionReason,
)
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

# The dashboard cache TTL has a 60 s floor: the frontend polls every 30 s, so at
# the configured 30 s default every poll re-runs the whole multi-query aggregate
# for marginal freshness. The floor still lets operators RAISE the TTL via
# ``dashboard_cache_ttl_seconds``; it only removes the too-low default. Applies
# to the metrics and attention dashboards alike — both are background telemetry.
_DASHBOARD_CACHE_TTL_FLOOR_SECONDS = 60


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
        counts = await repo.core_counts(recruiter_id)
        open_convs = counts["open_conversations"]
        hot_leads = counts["hot_leads"]
        pending_fu = counts["pending_followups"]
        failed_sends = counts["failed_sends"]
        bot_errors = counts["bot_errors"]
        bot_summary = await repo.bot_run_summary(recruiter_id)
        counts_by_stage = await repo.leads_by_stage(recruiter_id)
        human_convs = await repo.count_human_conversations(recruiter_id)

        # Same 24h window as bot_run_summary: the suppression rate is DERIVED
        # from the summary's counts (over terminal non-error outcomes — the
        # formula this rate has always used) so the success and suppression
        # tiles can never disagree about the window again.
        sent_count = int(bot_summary["sent"] or 0)
        suppressed_count = int(bot_summary["suppressed"] or 0)
        suppression = (
            suppressed_count / (sent_count + suppressed_count)
            if (sent_count + suppressed_count)
            else 0.0
        )

        # Concurrent-load monitoring (chatbot readiness). The RQ queue depth is a
        # sync-only read (RQ has no async client) → run it on a worker thread so
        # the dashboard never blocks the event loop (REL-02).
        queue_depth = await asyncio.to_thread(self._webhook_queue_depth)
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
            bot_suppression_rate=float(suppression),
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
            knowledge_ingest=await self._knowledge_ingest_health()
            if viewer.role == Role.admin
            else None,
            webhook_queue_depth=queue_depth,
            active_turns=active_turns_count,
            p95_bot_response_seconds=round(float(p95_latency), 1),
            turns_last_5min=recent_turns,
        )
        if cache_enabled:
            await cache_set_json(
                cache_key,
                metrics.model_dump(mode="json"),
                max(_DASHBOARD_CACHE_TTL_FLOOR_SECONDS, settings.dashboard_cache_ttl_seconds),
            )
        return metrics

    async def attention(self, viewer: User) -> AttentionDashboardOut:
        """Recruiter attention dashboard: exact counters + bounded queues.

        One Redis read on hit (prod-only); on miss, exactly 3 DB round-trips
        (counters + immediate rows + today rows) inside one transaction so all
        reads share a single snapshot (Phase 1 Read-transaction requirement).
        Rows include the full phone number for authenticated recruiters to
        contact candidates, but never the message body.
        """
        settings = get_settings()
        cache_enabled = settings.dashboard_cache_enabled and settings.app_env == "production"
        cache_scope = "admin" if viewer.role == Role.admin else f"recruiter:{viewer.id}"
        cache_key = f"dashboard:attention:{cache_scope}"
        if cache_enabled:
            cached = await cache_get_json(cache_key)
            if isinstance(cached, dict):
                # A corrupt payload (bad write, schema drift after a deploy) must
                # not 500 the dashboard until the key expires — fall through to a
                # fresh DB read instead. The bad value is overwritten below.
                try:
                    return AttentionDashboardOut.model_validate(cached)
                except ValidationError:
                    logger.warning(
                        "attention dashboard: malformed cached payload at %s, "
                        "falling back to DB read",
                        cache_key,
                        exc_info=True,
                    )

        recruiter_id = None if viewer.role == Role.admin else str(viewer.id)
        repo = DashboardRepository(self.db)

        # Snapshot consistency (Red-team Critical 3): get_db() yields a session
        # with no explicit transaction, so each SELECT would take a fresh READ
        # COMMITTED snapshot and a webhook write between queries could make
        # counters.needs_reply disagree with the immediate preview. REPEATABLE
        # READ on this session gives all reads one snapshot without fighting the
        # request-scoped session's autobegin semantics (a bare begin() here would
        # collide if the session already began implicitly). SET LOCAL scopes the
        # isolation to the current transaction and is cheap.
        #
        # The get_current_user dependency already ran a SELECT on this session to
        # load the viewer, autobeginning a read-only transaction. Postgres
        # requires SET TRANSACTION ISOLATION LEVEL to be the first statement of
        # its transaction, so roll back the autobegun transaction first; the SET
        # LOCAL below then opens a fresh transaction as its first statement, and
        # the repo reads inherit its REPEATABLE READ snapshot. Safe because the
        # viewer is fully read above and the repo uses raw SQL (no identity-map
        # dependency).
        await self.db.rollback()
        await self.db.execute(text("SET LOCAL transaction_isolation = 'repeatable read'"))

        # Round-trip budget: 3 (counters=1 + immediate=1 + today=1). No gather —
        # AsyncSession is not concurrency-safe across shared-session awaits.
        counters_map = await repo.attention_counters(recruiter_id)
        immediate_rows = await repo.attention_rows(recruiter_id, "immediate")
        today_rows = await repo.attention_rows(recruiter_id, "today")

        out = AttentionDashboardOut(
            updated_at=datetime.now(timezone.utc),
            counters=AttentionCounters(
                needs_reply=counters_map.get("needs_reply", 0),
                overdue=counters_map.get("overdue", 0),
                due_today=counters_map.get("due_today", 0),
                priority=counters_map.get("priority", 0),
                unread=counters_map.get("unread", 0),
            ),
            immediate=[self._attention_item(r) for r in immediate_rows],
            today=[self._attention_item(r) for r in today_rows],
        )
        if cache_enabled:
            await cache_set_json(
                cache_key,
                out.model_dump(mode="json"),
                max(_DASHBOARD_CACHE_TTL_FLOOR_SECONDS, settings.dashboard_cache_ttl_seconds),
            )
        return out

    @staticmethod
    def _attention_item(row) -> AttentionItemOut:
        """Map a repo attention row to the strict response schema.

        ``key`` and ``action`` are derived from the anchor: conversation-anchored
        rows get an ``OPEN_CONVERSATION`` action keyed by conversation id;
        lead-anchored rows (``zalo_id IS NULL``) get a ``CALL`` action keyed by
        ``lead:<id>``. Lead-anchored rows with a linked conversation still prefer
        the conversation key/action so the recruiter lands in the thread.
        """
        conversation_id = row.get("conversation_id")
        lead_id = row.get("lead_id")
        if conversation_id is not None:
            key = str(conversation_id)
            action = AttentionAction.OPEN_CONVERSATION
        elif lead_id is not None:
            key = f"lead:{lead_id}"
            action = AttentionAction.CALL
        else:
            # Defensive: a candidate must anchor on exactly one side. Should not
            # happen given the repo predicates, but never emit an empty key.
            key = "unknown"
            action = AttentionAction.OPEN_CONVERSATION
        return AttentionItemOut(
            key=key,
            reason=AttentionReason(row["reason"]),
            urgency_at=row["urgency_at"],
            conversation_id=conversation_id,
            lead_id=lead_id,
            name=row.get("name"),
            phone=row.get("phone"),
            desired_job=row.get("desired_job"),
            lead_stage=row.get("lead_stage"),
            lead_score=row.get("lead_score"),
            last_inbound_at=row.get("last_inbound_at"),
            due_at=row.get("due_at"),
            delivery_status=row.get("delivery_status"),
            action=action,
        )

    async def _knowledge_ingest_health(self) -> KnowledgeIngestHealth:
        """Admin-only health snapshot for the async knowledge ingest pipeline."""
        repo = DashboardRepository(self.db)
        counts = await repo.knowledge_stage_counts()
        processing_stages = (
            "UPLOADED",
            "EXTRACTED",
            "DIGESTING",
            "EMBEDDING",
            "INDEXING",
            "PROCESSING",
        )
        processing_count = sum(counts.get(stage, 0) for stage in processing_stages)
        stuck_count = int(await repo.count_stuck_documents(list(processing_stages)) or 0)
        issue_rows = await repo.recent_ingest_issues(list(processing_stages))
        # Sync-only Redis reads → worker thread (REL-02), same as the webhook depth.
        queue_depth, failed_job_count, worker_count = await asyncio.to_thread(
            self._rq_ingest_counts
        )
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
        """Current depth of the webhook_high RQ queue (messages waiting for a worker slot).

        Sync by design (RQ needs the blocking client) — callers run it via
        ``asyncio.to_thread`` so it never occupies the event loop (REL-02).
        """
        try:
            from rq import Queue

            from app.core.redis import get_redis_sync

            return Queue("webhook_high", connection=get_redis_sync()).count
        except Exception:  # noqa: BLE001 — Redis telemetry must not break dashboard
            logger.warning("failed to read webhook_high queue depth", exc_info=True)
            return 0

    def _rq_ingest_counts(self) -> tuple[int, int, int]:
        """Ingest-queue depth / failed jobs / live workers. Sync: call via ``to_thread``."""
        try:
            from app.core.redis import get_redis_sync

            redis = get_redis_sync()
            queue_depth = int(redis.llen("rq:queue:ingest") or 0)
            failed_job_count = int(redis.zcard("rq:failed:ingest") or 0)
            worker_count = int(redis.scard("rq:workers:ingest") or 0)
            return queue_depth, failed_job_count, worker_count
        except Exception:  # noqa: BLE001 — Redis telemetry must not break dashboard
            return 0, 0, 0
