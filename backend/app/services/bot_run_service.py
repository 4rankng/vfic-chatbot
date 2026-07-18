"""Read-only bot-run listing (the takeover race-guard audit trail)."""

from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import BotRun, BotRunOutcome
from app.schemas.bot_run import (
    BotRunTraceDetailOut,
    BotRunTraceSummaryOut,
    parse_decision_trace,
)


class BotRunService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(
        self,
        *,
        conversation_id: uuid.UUID | None = None,
        outcome: BotRunOutcome | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list[BotRun], int]:
        q = select(BotRun)
        if conversation_id is not None:
            q = q.where(BotRun.conversation_id == conversation_id)
        if outcome is not None:
            q = q.where(BotRun.outcome == outcome)
        total = await self.db.scalar(select(func.count()).select_from(q.subquery()))
        rows = (
            await self.db.scalars(
                q.order_by(desc(BotRun.started_at), desc(BotRun.id))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def list_conversation_trace_summaries(
        self,
        *,
        conversation_id: uuid.UUID,
        page: int = 1,
        per_page: int = 10,
    ) -> tuple[list[BotRunTraceSummaryOut], int]:
        q = (
            select(
                BotRun.id,
                BotRun.conversation_id,
                BotRun.started_at,
                BotRun.ended_at,
                BotRun.outcome,
                BotRun.decision_trace,
            )
            .where(BotRun.conversation_id == conversation_id)
            .order_by(desc(BotRun.started_at), desc(BotRun.id))
        )
        total = await self.db.scalar(
            select(func.count()).select_from(
                select(BotRun.id).where(BotRun.conversation_id == conversation_id).subquery()
            )
        )
        rows = (await self.db.execute(q.offset((page - 1) * per_page).limit(per_page))).mappings().all()
        summaries = [
            BotRunTraceSummaryOut(
                id=row["id"],
                conversation_id=row["conversation_id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                outcome=row["outcome"],
                trace_available=parse_decision_trace(row["decision_trace"]) is not None,
            )
            for row in rows
        ]
        return summaries, int(total or 0)

    async def get_trace_detail(self, run_id: int) -> BotRunTraceDetailOut | None:
        row = (
            await self.db.execute(
                select(
                    BotRun.id,
                    BotRun.conversation_id,
                    BotRun.started_at,
                    BotRun.ended_at,
                    BotRun.outcome,
                    BotRun.decision_trace,
                ).where(BotRun.id == run_id)
            )
        ).mappings().first()
        if row is None:
            return None
        trace = parse_decision_trace(row["decision_trace"])
        return BotRunTraceDetailOut(
            id=row["id"],
            conversation_id=row["conversation_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            outcome=row["outcome"],
            trace_available=trace is not None,
            decision_trace=trace,
        )
