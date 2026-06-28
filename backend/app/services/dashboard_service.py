"""Dashboard metrics: open conversations, hot leads, pending follow-ups, bot
suppression rate, failed sends, bot errors. Scoped to the viewer (admin = global,
recruiter = assigned)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Role, User
from app.schemas.job import DashboardMetrics, KnowledgeIngestHealth

# Canonical recruitment-funnel order (mirrors the leads.lead_stage CHECK
# constraint + the frontend LEAD_STAGES list). Used to emit stage_breakdown in a
# stable order including zero-count stages, so the client never has to sort.
_LEAD_STAGE_ORDER = (
    "NEW",
    "ENGAGED",
    "QUALIFIED",
    "APPLIED",
    "HIRED",
    "LOST",
    "UNQUALIFIED",
)


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def metrics(self, viewer: User) -> DashboardMetrics:
        # Every count is scoped to the viewer: admin = global, recruiter = assigned
        # to them or unassigned. The previous version left pending_followups,
        # failed_zalo_sends, bot_errors and the suppression rate unscoped, so a
        # recruiter saw global (cross-recruiter) numbers for those tiles.
        if viewer.role == Role.admin:
            open_convs = await self.db.scalar(text("SELECT count(*) FROM conversations WHERE status = 'OPEN'"), {})
            hot_leads = await self.db.scalar(text("SELECT count(*) FROM leads WHERE lead_score = 'hot'"), {})
            pending_fu = await self.db.scalar(text("SELECT count(*) FROM follow_up_tasks WHERE status = 'PENDING'"), {})
            failed_sends = await self.db.scalar(text("SELECT count(*) FROM messages WHERE delivery_status = 'FAILED'"), {})
            bot_errors = await self.db.scalar(text("SELECT count(*) FROM bot_runs WHERE outcome = 'ERROR'"), {})
            suppression = (
                await self.db.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
                        "FROM bot_runs WHERE outcome IN ('SENT','SUPPRESSED')"
                    )
                )
            ).scalar()
        else:
            p = {"uid": str(viewer.id)}
            lead_scope = "(l.assigned_recruiter_id = :uid OR l.assigned_recruiter_id IS NULL)"
            conv_scope = "(c.assigned_recruiter_id = :uid OR c.assigned_recruiter_id IS NULL)"
            open_convs = await self.db.scalar(
                text(f"SELECT count(*) FROM conversations c WHERE c.status = 'OPEN' AND {conv_scope}"), p
            )
            hot_leads = await self.db.scalar(
                text(f"SELECT count(*) FROM leads l WHERE l.lead_score = 'hot' AND {lead_scope}"), p
            )
            pending_fu = await self.db.scalar(
                text(
                    "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
                    f"WHERE f.status = 'PENDING' AND {lead_scope}"
                ),
                p,
            )
            failed_sends = await self.db.scalar(
                text(
                    "SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                    f"WHERE m.delivery_status = 'FAILED' AND {conv_scope}"
                ),
                p,
            )
            bot_errors = await self.db.scalar(
                text(
                    "SELECT count(*) FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
                    f"WHERE b.outcome = 'ERROR' AND {conv_scope}"
                ),
                p,
            )
            suppression = (
                await self.db.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE b.outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
                        "FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
                        f"WHERE b.outcome IN ('SENT','SUPPRESSED') AND {conv_scope}"
                    ),
                    p,
                )
            ).scalar()

        # Lead funnel + human-takeover count, scoped identically to the tiles
        # above (admin = global, recruiter = assigned-or-unassigned). One GROUP
        # BY replaces the client-side dump-and-count over the whole pipeline.
        if viewer.role == Role.admin:
            lead_where = ""
            lead_params: dict = {}
            human_where = "WHERE mode = 'HUMAN'"
            human_params: dict = {}
        else:
            uid = str(viewer.id)
            lead_scope = "(assigned_recruiter_id = :uid OR assigned_recruiter_id IS NULL)"
            lead_where = f"WHERE {lead_scope}"
            lead_params = {"uid": uid}
            human_where = f"WHERE mode = 'HUMAN' AND {lead_scope}"
            human_params = {"uid": uid}

        stage_rows = (
            await self.db.execute(
                text(f"SELECT lead_stage, count(*) FROM leads {lead_where} GROUP BY lead_stage"),
                lead_params,
            )
        ).all()
        counts_by_stage: dict[str, int] = {r[0]: int(r[1]) for r in stage_rows}
        total_leads = sum(counts_by_stage.values())
        qualified_count = counts_by_stage.get("QUALIFIED", 0)
        hired_count = counts_by_stage.get("HIRED", 0)
        human_convs = await self.db.scalar(
            text(f"SELECT count(*) FROM conversations {human_where}"), human_params
        )
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

        return DashboardMetrics(
            open_conversations=int(open_convs or 0),
            hot_leads=int(hot_leads or 0),
            pending_followups=int(pending_fu or 0),
            bot_suppression_rate=float(suppression or 0.0),
            failed_zalo_sends=int(failed_sends or 0),
            bot_errors=int(bot_errors or 0),
            total_leads=total_leads,
            qualified_count=qualified_count,
            hired_count=hired_count,
            hired_rate=round(hired_count / total_leads * 100) if total_leads else 0.0,
            unread_conversation_count=int(human_convs or 0),
            stage_breakdown=stage_breakdown,
            knowledge_ingest=await self._knowledge_ingest_health() if viewer.role == Role.admin else None,
        )

    async def _knowledge_ingest_health(self) -> KnowledgeIngestHealth:
        """Admin-only health snapshot for the async knowledge ingest pipeline."""
        stage_rows = (
            await self.db.execute(
                text(
                    "SELECT stage, count(*) "
                    "FROM knowledge_documents "
                    "GROUP BY stage ORDER BY stage"
                )
            )
        ).all()
        counts = {str(row[0]): int(row[1]) for row in stage_rows}
        processing_stages = ("UPLOADED", "EXTRACTED", "DIGESTING", "EMBEDDING", "INDEXING", "PROCESSING")
        processing_count = sum(counts.get(stage, 0) for stage in processing_stages)
        stuck_count = int(
            await self.db.scalar(
                text(
                    "SELECT count(*) FROM knowledge_documents "
                    "WHERE stage = ANY(CAST(:stages AS text[])) "
                    "AND updated_at < now() - interval '10 minutes'"
                ),
                {"stages": list(processing_stages)},
            )
            or 0
        )
        issue_rows = (
            await self.db.execute(
                text(
                    "SELECT id, file_name, project_id, status, stage, "
                    "GREATEST(0, floor(extract(epoch from (now() - updated_at)) / 60))::int AS minutes_since_update, "
                    "left(coalesce(error, ''), 240) AS error "
                    "FROM knowledge_documents "
                    "WHERE status = 'FAILED' "
                    "OR (stage = ANY(CAST(:stages AS text[])) AND updated_at < now() - interval '10 minutes') "
                    "ORDER BY updated_at DESC LIMIT 6"
                ),
                {"stages": list(processing_stages)},
            )
        ).mappings()
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
