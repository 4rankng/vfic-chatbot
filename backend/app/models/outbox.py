"""Outbound outbox ORM model (Tech-Lead Directive §14)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OutboxStatus(str, enum.Enum):
    """Dispatch status for an outbound message.

    Mirrors ``DeliveryStatus`` for messages but tracks the *dispatch* step
    specifically. The inline send path records the final state directly; only
    crashes leave rows in SENDING (which the sweep re-dispatches).
    """

    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SEND_UNKNOWN = "SEND_UNKNOWN"
    SUPPRESSED = "SUPPRESSED"


class OutboxOriginKind(str, enum.Enum):
    BOT = "BOT"
    PROACTIVE = "PROACTIVE"
    MANUAL = "MANUAL"


class OutboxFenceScope(str, enum.Enum):
    RUNTIME = "RUNTIME"
    CHANNEL = "CHANNEL"


class OutboundOutbox(Base):
    """Transactional outbox row for one outbound BOT message.

    One row per outbound message (unique on ``message_id``). Written in the
    same transaction as ``record_bot_outcome`` so the outbox reflects the
    committed send outcome atomically. See ``outbox_service.py``.
    """

    __tablename__ = "outbound_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    zalo_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT"),
    )
    authority_generation: Mapped[int | None] = mapped_column(BigInteger)
    runtime_fingerprint: Mapped[str | None] = mapped_column(String(64))
    origin_kind: Mapped[str | None] = mapped_column(String(24))
    fence_scope: Mapped[str | None] = mapped_column(String(24))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
