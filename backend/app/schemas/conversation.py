"""Conversation / message schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.conversation import (
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    MessageSender,
)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    zalo_chat_id: str
    zalo_channel: str = "bot"
    mode: ConversationMode
    status: ConversationStatus
    needs_human: bool
    version: int
    assigned_recruiter_id: uuid.UUID | None = None
    taken_over_at: datetime | None = None
    unread_count: int
    bot_locked_until: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    data: list[ConversationOut]
    total: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: uuid.UUID
    sender: MessageSender
    body: str
    recruiter_id: uuid.UUID | None = None
    bot_run_id: int | None = None
    delivery_status: DeliveryStatus
    zalo_message_id: str | None = None
    external_error: str | None = None
    delivery_attempts: int = 0
    created_at: datetime


class MessageListResponse(BaseModel):
    data: list[MessageOut]
    total: int


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
