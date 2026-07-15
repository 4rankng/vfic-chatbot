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
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    Text,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.contact import Contact, ContactChannelIdentity


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
    # SENDING: an atomic pre-send claim flipped the pending BOT row just before the
    # Zalo POST. Transient during a normal turn; if a worker crashes between the
    # send and the SENT write, reconcile treats a stale SENDING row as
    # sent-but-unconfirmed (at-most-once) instead of re-enqueuing a duplicate.
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    DELIVERED = "DELIVERED"
    READ = "READ"
    # SEND_UNKNOWN: the Zalo POST raised a transport exception (timeout / reset)
    # AFTER the request may have reached Zalo. Non-retriable — the reconciler skips
    # these rows (blindly re-running would risk a duplicate reply). Surfaced on the
    # recruiter console for manual confirm/cancel. Conservative classifier (the
    # blanket "unknown" catch-all also lands here) biases toward at-most-once.
    SEND_UNKNOWN = "SEND_UNKNOWN"


class BotRunOutcome(str, enum.Enum):
    SENT = "SENT"
    SUPPRESSED = "SUPPRESSED"
    ERROR = "ERROR"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "channel_identity_id IS NULL OR contact_id IS NOT NULL",
            name="conversation_identity_requires_contact",
        ),
        ForeignKeyConstraint(
            ["channel_identity_id", "contact_id"],
            ["contact_channel_identities.id", "contact_channel_identities.contact_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_conversations_contact",
            "contact_id",
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index(
            "uq_conversations_channel_identity",
            "channel_identity_id",
            unique=True,
            postgresql_where=text("channel_identity_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    zalo_chat_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    # Channel badge/source for the user-visible Zalo inbox. New channel-aware
    # conversations scope zalo_chat_id as "{channel}:{external_id}".
    zalo_channel: Mapped[str] = mapped_column(
        String, nullable=False, default="bot", server_default="bot", index=True
    )
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
    # Strict per-conversation monotonic counter for debugging — increments on
    # EVERY mutation (inbound, bot outcome, receipt, recruiter action, mode
    # change), unlike `version` which intentionally skips bot outcomes to avoid
    # invalidating in-flight optimistic-lock guards. Used to answer "did B
    # process before A?" without ambiguity. Pure observability — no guard logic
    # consumes it.
    conversation_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default=text("1")
    )
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT")
    )
    channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    contact: Mapped["Contact | None"] = relationship(lazy="selectin", foreign_keys=[contact_id])
    channel_identity: Mapped["ContactChannelIdentity | None"] = relationship(
        lazy="selectin", foreign_keys=[channel_identity_id], overlaps="contact"
    )
    unread_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    bot_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bot_lock_owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    bot_lock_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- proactive follow-up state ---
    followup_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_followup_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_opted_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

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
    # Per-stage wall-clock timing (ms) captured by run_turn for the performance
    # dashboard: webhook_to_pickup_ms / preamble_ms / lane / lead_ms /
    # llm_queue_ms / llm_model_ms / safety_ms / send_ms / total_ms (+ queue_depth,
    # intent, llm_calls, llm_call_ms[], prompt/completion/cached_tokens,
    # tool_breakdown{}, retried_429, degraded). Nullable — older
    # runs and any path that skips a stage simply omit the key. Aggregated via
    # percentile_cont over (stage_timings->>'<key>')::int.
    stage_timings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Webhook request_id propagated through the RQ job dict + BotRunState so one
    # trace_id query returns every log line for a single candidate message's
    # journey (webhook → RQ → LangGraph → Zalo send). Nullable — legacy runs and
    # direct/test turns may not stamp it. Indexed for log-correlation queries.
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Phase 4 FAQ-bypass provenance: similarity_score, runner_up_score,
    # decision_threshold, faq_document_id, abstained (bool). Surfaces the
    # abstention rate on the performance dashboard to tune the margin.
    outcome_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


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

    @property
    def delivery_attempts(self) -> int:
        """Best-known number of sends for this message's durable command.

        The outbox owns this operational value. Repository and state code attach
        it when available; inbound and legacy messages intentionally report 0.
        """
        return int(getattr(self, "_delivery_attempts", 0) or 0)
