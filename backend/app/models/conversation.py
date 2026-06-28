"""Conversation / message / bot-run / outbound ORM models (mirror Alembic baseline)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConversationMode(str, enum.Enum):
    BOT = "BOT"
    HUMAN = "HUMAN"
    SEMI_AUTO = "SEMI_AUTO"
    CLOSED = "CLOSED"


class ConversationStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MessageSender(str, enum.Enum):
    WORKER = "WORKER"
    BOT = "BOT"
    RECRUITER = "RECRUITER"
    SYSTEM = "SYSTEM"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"


class BotRunOutcome(str, enum.Enum):
    SENT = "SENT"
    SUPPRESSED = "SUPPRESSED"
    ERROR = "ERROR"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    zalo_chat_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    mode: Mapped[ConversationMode] = mapped_column(
        Enum(ConversationMode, name="conversation_mode", create_type=False),
        nullable=False,
        default=ConversationMode.BOT,
        server_default="BOT",
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", create_type=False),
        nullable=False,
        default=ConversationStatus.OPEN,
        server_default="OPEN",
    )
    needs_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    unread_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    bot_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BotRun(Base):
    __tablename__ = "bot_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version_at_start: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_reply: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[BotRunOutcome] = mapped_column(
        Enum(BotRunOutcome, name="bot_run_outcome", create_type=False), nullable=False
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender: Mapped[MessageSender] = mapped_column(
        Enum(MessageSender, name="message_sender", create_type=False), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    bot_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bot_runs.id", ondelete="SET NULL")
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status", create_type=False),
        nullable=False,
        default=DeliveryStatus.SENT,
        server_default="SENT",
    )
    zalo_message_id: Mapped[str | None] = mapped_column(String)
    external_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    expected_conversation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id"))
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status", create_type=False),
        nullable=False,
        default=DeliveryStatus.PENDING,
        server_default="PENDING",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
