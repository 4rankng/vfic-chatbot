"""Conversation / message schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.conversation_messaging.domain.statuses import (
    ConversationMode,
    ConversationProjectState,
    ConversationStatus,
    DeliveryStatus,
    MessageSender,
)
from app.schemas.contacts import ChannelIdentitySummaryOut, ContactSummaryOut


def _mask_external_id(value: str | None) -> str | None:
    """Mask all but the last 4 chars of an external participant id.

    Raw Messenger PSIDs / Zalo chat ids never reach the recruiter API; the
    backend projects this masked suffix instead. Short values collapse to a
    fixed mask so the original length is not recoverable.
    """
    if value is None:
        return None
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


class ConversationOut(BaseModel):
    """Recruiter-facing conversation projection.

    Neutral fields (``channel_provider``, ``channel_account_label``,
    ``participant_display_id``, ``provider_message_id``) are the canonical
    channel-neutral surface. ``zalo_chat_id`` / ``zalo_channel`` remain as
    nullable compatibility aliases populated only for Zalo rows; Messenger
    conversations carry NULL ``zalo_chat_id``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Zalo compatibility aliases (Alembic 0047): nullable for Messenger rows.
    zalo_chat_id: str | None = None
    zalo_channel: str = "bot"
    mode: ConversationMode
    status: ConversationStatus
    needs_human: bool
    version: int
    assigned_recruiter_id: uuid.UUID | None = None
    project_context_state: ConversationProjectState = ConversationProjectState.EXPLORE
    focused_project_id: uuid.UUID | None = None
    # Canonical neutral identity (NOT NULL after Alembic 0047 backfill).
    contact_id: uuid.UUID | None = None
    channel_identity_id: uuid.UUID | None = None
    contact: ContactSummaryOut | None = None
    channel_identity: ChannelIdentitySummaryOut | None = None
    taken_over_at: datetime | None = None
    unread_count: int
    bot_locked_until: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def channel_provider(self) -> str | None:
        """Neutral provider id (e.g. zalo_bot / zalo_oa / facebook_messenger)."""
        ident = self.channel_identity
        return ident.provider if ident is not None else None

    @computed_field  # type: ignore[misc]
    @property
    def channel_display(self) -> str | None:
        """Badge channel: the TingTing support OA narrowed inside zalo_oa.

        Derived server-side from the raw account_key (see
        ChannelIdentitySummaryOut) because the masked account_key that reaches
        a client cannot distinguish the two Zalo OA accounts.
        """
        ident = self.channel_identity
        return ident.display_channel if ident is not None else None

    @computed_field  # type: ignore[misc]
    @property
    def channel_account_label(self) -> str | None:
        """Safe account display label. Falls back to the provider id."""
        # The full ChannelAccount.label is joined in by the API layer when
        # available; the identity's account_key is a stable fallback but may
        # carry an external id, so prefer not to surface it raw.
        return self.channel_provider

    @computed_field  # type: ignore[misc]
    @property
    def participant_display_id(self) -> str | None:
        """Masked external participant id — raw PSID/chat id never leaves the API."""
        ident = self.channel_identity
        return _mask_external_id(ident.external_id) if ident is not None else None


class ConversationListResponse(BaseModel):
    data: list[ConversationOut]
    total: int


class MessageOut(BaseModel):
    """Recruiter-facing message projection.

    ``provider_message_id`` is the canonical neutral id (Graph API mid for
    Messenger, Zalo message id for Zalo). ``zalo_message_id`` remains as a
    nullable compatibility alias populated only for Zalo rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: uuid.UUID
    sender: MessageSender
    body: str
    recruiter_id: uuid.UUID | None = None
    bot_run_id: int | None = None
    delivery_status: DeliveryStatus
    # Canonical neutral message id (Alembic 0047).
    provider_message_id: str | None = None
    # Zalo compatibility alias — same value as provider_message_id for Zalo rows.
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
