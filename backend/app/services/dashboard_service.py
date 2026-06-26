"""Dashboard metrics: open conversations, hot leads, pending follow-ups, bot
suppression rate, failed sends, bot errors. Scoped to the viewer (admin = global,
recruiter = assigned)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Role, User
from app.schemas.job import DashboardMetrics

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
        )
