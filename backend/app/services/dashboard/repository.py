"""Data-access layer for dashboard metrics.

Verbatim ports of the count / funnel / ingest-health queries DashboardService
previously ran inline, so the service owns only viewer-scoping + result assembly
(business logic) and the Redis telemetry call.

Each metric branches on ``recruiter_id``: ``None`` = global (admin), a uid = scoped
to that recruiter's assigned-or-unassigned rows. The "admin = global, recruiter =
assigned" rule is decided by the SERVICE and passed in; this repo just runs the SQL.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.viewer_scope import viewer_scope_sql


class DashboardRepository:
    """Read-only dashboard counts, funnel, and ingest-health queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count_open_conversations(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM conversations WHERE status = 'OPEN'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM conversations c "
                "WHERE c.status = 'OPEN' "
                "AND " + viewer_scope_sql("c.")
            ),
            {"uid": recruiter_id},
        )

    async def count_hot_leads(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM leads WHERE lead_score = 'hot'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM leads l "
                "WHERE l.lead_score = 'hot' "
                "AND " + viewer_scope_sql("l.")
            ),
            {"uid": recruiter_id},
        )

    async def count_pending_followups(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM follow_up_tasks WHERE status = 'PENDING'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
                "WHERE f.status = 'PENDING' "
                "AND " + viewer_scope_sql("l.")
            ),
            {"uid": recruiter_id},
        )

    async def count_failed_sends(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM messages WHERE delivery_status = 'FAILED'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.delivery_status = 'FAILED' "
                "AND " + viewer_scope_sql("c.")
            ),
            {"uid": recruiter_id},
        )

    async def count_bot_errors(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM bot_runs WHERE outcome = 'ERROR'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
                "WHERE b.outcome = 'ERROR' "
                "AND " + viewer_scope_sql("c.")
            ),
            {"uid": recruiter_id},
        )

    async def bot_run_summary(self, recruiter_id: str | None = None) -> dict[str, float | int]:
        """Aggregate bot-turn health without downloading the bot_run audit log."""
        sql = (
            "SELECT "
            "count(*)::int AS total, "
            "count(*) FILTER (WHERE b.outcome = 'SENT')::int AS sent, "
            "count(*) FILTER (WHERE b.outcome = 'SUPPRESSED')::int AS suppressed, "
            "count(*) FILTER (WHERE b.outcome = 'ERROR')::int AS errors, "
            "coalesce(avg(extract(epoch FROM (b.ended_at - b.started_at))) "
            "FILTER (WHERE b.ended_at IS NOT NULL), 0)::float AS avg_seconds "
            "FROM bot_runs b"
        )
        params = {}
        if recruiter_id is not None:
            sql += (
                " JOIN conversations c ON c.id = b.conversation_id "
                "WHERE " + viewer_scope_sql("c.")
            )
            params["uid"] = recruiter_id
        row = (await self.db.execute(text(sql), params)).mappings().one()
        return {
            "total": int(row["total"] or 0),
            "sent": int(row["sent"] or 0),
            "suppressed": int(row["suppressed"] or 0),
            "errors": int(row["errors"] or 0),
            "avg_seconds": float(row["avg_seconds"] or 0.0),
        }

    async def bot_suppression_rate(self, recruiter_id: str | None = None) -> float | None:
        if recruiter_id is None:
            return (
                await self.db.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
                        "FROM bot_runs WHERE outcome IN ('SENT','SUPPRESSED')"
                    )
                )
            ).scalar()
        return (
            await self.db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE b.outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
                    "FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
                    "WHERE b.outcome IN ('SENT','SUPPRESSED') "
                    "AND " + viewer_scope_sql("c.")
                ),
                {"uid": recruiter_id},
            )
        ).scalar()

    async def leads_by_stage(self, recruiter_id: str | None = None) -> dict[str, int]:
        if recruiter_id is None:
            rows = (
                await self.db.execute(text("SELECT lead_stage, count(*) FROM leads GROUP BY lead_stage"))
            ).all()
        else:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT lead_stage, count(*) FROM leads "
                        "WHERE " + viewer_scope_sql("") + " "
                        "GROUP BY lead_stage"
                    ),
                    {"uid": recruiter_id},
                )
            ).all()
        return {r[0]: int(r[1]) for r in rows}

    async def count_human_conversations(self, recruiter_id: str | None = None) -> int | None:
        if recruiter_id is None:
            return await self.db.scalar(text("SELECT count(*) FROM conversations WHERE mode = 'HUMAN'"))
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM conversations "
                "WHERE mode = 'HUMAN' AND " + viewer_scope_sql("")
            ),
            {"uid": recruiter_id},
        )

    async def knowledge_stage_counts(self) -> dict[str, int]:
        """``{stage: count}`` for all knowledge_documents (admin ingest health)."""
        rows = (
            await self.db.execute(
                text("SELECT stage, count(*) FROM knowledge_documents GROUP BY stage ORDER BY stage")
            )
        ).all()
        return {str(r[0]): int(r[1]) for r in rows}

    async def count_stuck_documents(self, stages: list[str]) -> int | None:
        """Docs in a processing stage not updated for >10 min."""
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM knowledge_documents "
                "WHERE stage = ANY(CAST(:stages AS text[])) "
                "AND updated_at < now() - interval '10 minutes'"
            ),
            {"stages": stages},
        )

    async def recent_ingest_issues(self, stages: list[str], limit: int = 6) -> list:
        """FAILED or stuck documents, newest first (mapping rows for the service to format)."""
        return (
            await self.db.execute(
                text(
                    "SELECT id, file_name, project_id, status, stage, "
                    "GREATEST(0, floor(extract(epoch from (now() - updated_at)) / 60))::int AS minutes_since_update, "
                    "left(coalesce(error, ''), 240) AS error "
                    "FROM knowledge_documents "
                    "WHERE status = 'FAILED' "
                    "OR (stage = ANY(CAST(:stages AS text[])) AND updated_at < now() - interval '10 minutes') "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"stages": stages, "limit": limit},
            )
        ).mappings()

    # --- Concurrent-load monitoring (300-concurrency readiness) ---

    async def active_turns(self) -> int:
        """Conversations currently processing a bot turn (lock held)."""
        return await self.db.scalar(
            text("SELECT count(*) FROM conversations WHERE bot_locked_until > now()")
        ) or 0

    async def bot_run_p95_latency(self, days: int = 7) -> float:
        """95th percentile turn duration (seconds) from completed bot_runs in the last *days* days."""
        return float(
            await self.db.scalar(
                text(
                    "SELECT coalesce(percentile_cont(0.95) "
                    "WITHIN GROUP (ORDER BY extract(epoch FROM (ended_at - started_at))), 0) "
                    "FROM bot_runs "
                    "WHERE outcome IN ('SENT','SUPPRESSED') "
                    "AND started_at > now() - make_interval(days => :days) "
                    "AND ended_at IS NOT NULL"
                ),
                {"days": days},
            )
            or 0.0
        )

    async def recent_turns_count(self, minutes: int = 5) -> int:
        """Bot turns started in the last N minutes (near-real-time throughput)."""
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM bot_runs "
                "WHERE started_at > now() - make_interval(mins => :minutes)"
            ),
            {"minutes": minutes},
        ) or 0


__all__ = ["DashboardRepository"]
