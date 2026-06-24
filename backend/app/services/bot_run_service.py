"""Read-only bot-run listing (the takeover race-guard audit trail)."""
from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import BotRun, BotRunOutcome


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
