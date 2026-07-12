"""Bot-run schemas (read-only ops audit trail)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.conversation import BotRunOutcome


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
