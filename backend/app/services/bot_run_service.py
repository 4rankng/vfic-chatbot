"""Read-only bot-run listing (the takeover race-guard audit trail)."""

from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import BotRun, BotRunOutcome
from app.schemas.bot_run import BotRunDetailOut


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

    async def get_run_detail(self, run_id: int) -> BotRunDetailOut | None:
        row = (
            await self.db.execute(
                select(
                    BotRun.id,
                    BotRun.conversation_id,
                    BotRun.started_at,
                    BotRun.ended_at,
                    BotRun.outcome,
                ).where(BotRun.id == run_id)
            )
        ).mappings().first()
        if row is None:
            return None
        return BotRunDetailOut(
            id=row["id"],
            conversation_id=row["conversation_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            outcome=row["outcome"],
        )
