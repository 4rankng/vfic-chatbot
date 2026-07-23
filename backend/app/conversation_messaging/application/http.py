"""HTTP-facing contracts for conversation messaging routes."""

from __future__ import annotations

import uuid
from typing import Protocol, TypedDict

from app.conversation_messaging.domain.statuses import ConversationMode


class ConversationHttpRecord(Protocol):
    id: uuid.UUID
    version: int
    assigned_recruiter_id: uuid.UUID | None
    mode: ConversationMode


class InlineWebChatTurnResult(TypedDict):
    outcome: str | None
    reply: str | None
    conversation_id: str
