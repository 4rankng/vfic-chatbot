"""Bot-run schemas (read-only ops audit trail)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.conversation_messaging.domain.statuses import BotRunOutcome


class BotRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    version_at_start: int
    proposed_reply: str | None = None
    outcome: BotRunOutcome


class BotRunListResponse(BaseModel):
    data: list[BotRunOut]
    total: int


class BotRunDetailOut(BaseModel):
    """One bot run's facts — no execution summary."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    outcome: BotRunOutcome
