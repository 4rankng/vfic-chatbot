"""Conversation / message / bot-run / outbound ORM models (mirror Alembic baseline)."""

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
from app.conversation_messaging.domain.statuses import (
    BotRunOutcome,
    ConversationMode,
    ConversationProjectState,
    ConversationStatus,
    DeliveryStatus,
    MessageSender,
)


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
    # Zalo compatibility alias (Alembic 0047): nullable for Messenger rows,
    # which carry no Zalo chat id. UNIQUE constraint still holds for non-NULL
    # Zalo values (Postgres allows multiple NULLs). The canonical identifier is
    # now (channel_identity_id, contact_id) below.
    zalo_chat_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
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
    project_context_state: Mapped[ConversationProjectState] = mapped_column(
        String(16),
        nullable=False,
        default=ConversationProjectState.EXPLORE,
        server_default="EXPLORE",
    )
    focused_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
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
    # Canonical channel identity (Alembic 0047): NOT NULL after backfill.
    # Every conversation belongs to exactly one ContactChannelIdentity + Contact;
    # the composite FK to contact_channel_identities(id, contact_id) is declared
    # in __table_args__ above.
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    channel_identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
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

    # First-touch source of the thread: how the candidate entered —
    # {"kind": "post_link", "post_code": "BV1026"} from a Zalo prefill link
    # (``https://zalo.me/<oa>?text=%23<CODE>``), or {"kind": "referral", ...}
    # from a Messenger referral (Meta ``ad_id`` / ads ``post_id`` / m.me ``ref``).
    # Written by the inbound path on the first touch that carries a source;
    # later touches only fill keys the record is still missing (first touch
    # wins). Read-only on the recruiter API. Nullable for pre-0069 rows.
    attribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Retired proactive-follow-up bookkeeping. These columns survive the 2026-10-04
    # removal of the proactive feature and are now read/written by nothing on the
    # bot path. ``followup_opted_out`` is the exception and is still load-bearing: the
    # inbound opt-out phrase match and the recruiter stop action both set it, and it
    # is a user-facing privacy control. The other three are dead weight pending a
    # column migration — do not add new readers.
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
    runtime_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT"),
    )
    authority_generation: Mapped[int | None] = mapped_column(BigInteger)
    runtime_fingerprint: Mapped[str | None] = mapped_column(String(64))
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
    # Provider-neutral message id (Alembic 0047). Backfilled from zalo_message_id
    # for Zalo rows; Messenger rows use the Graph API mid. The scoped partial
    # unique index uq_messages_conv_provider_message on (conversation_id,
    # provider_message_id) is the durable inbound idempotency boundary.
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    external_error: Mapped[str | None] = mapped_column(Text)
    runtime_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT"),
    )
    authority_generation: Mapped[int | None] = mapped_column(BigInteger)
    runtime_fingerprint: Mapped[str | None] = mapped_column(String(64))
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
