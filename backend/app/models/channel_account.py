"""Channel account registry model — neutral (provider, account_key) authority.

Mirrors the ``channel_accounts`` table created by Alembic revision
``0047_canonical_channel_identity``. This is the durable channel-account
registry: one row per connected provider/account (e.g. Zalo Bot, Zalo OA,
one active Facebook Page). Encrypted credentials stay in
:class:`IntegrationSetting` under an account-scoped namespace; this model
holds only safe display/lifecycle/authority data.

Phase 2 introduces the model and backfills two stable Zalo accounts. Phase 4
adds the Facebook OAuth/Page-lifecycle surface on top of it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChannelAccount(Base):
    """Neutral channel-account authority record.

    Lifecycle:

    - ``ACTIVE``  — resolves send authority; full recruiter parity.
    - ``INACTIVE`` — readable history scope (archived Page); never resolves
      send authority. Disconnect/replacement moves a row here without deleting
      its contacts/conversations/history.

    ``generation`` is the authority epoch advanced on connect/reconnect/
    disconnect. A stale outbound command (queued across a lifecycle change)
    compares its stamped generation to the active one and suppresses itself
    rather than sending under a superseded account.

    The partial unique index ``uq_channel_accounts_one_active_per_account``
    (created in the migration, not expressible as a column-level ORM
    constraint) enforces at most one ACTIVE row per (provider, account_key) —
    a Page cannot be active twice, but many Pages may each be active (multi-
    Page rollout, Alembic 0054).
    """

    __tablename__ = "channel_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="channel_account_status_values"),
        CheckConstraint(
            "provider ~ '^[a-z0-9][a-z0-9._-]*$'", name="channel_account_provider_canonical"
        ),
        Index("ix_channel_accounts_provider_status", "provider", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_key: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # Provider-safe metadata only: e.g. Facebook Page category, last health
    # check status. Never tokens, raw webhook payloads, or PII.
    provider_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"


class ChannelAccountProject(Base):
    """Page/Project mapping — one row per (channel account, Project).

    Scopes each conversation's Project catalog to the Facebook Page the
    conversation came from (multi-Page rollout, Alembic 0054). Mappings are
    independent of account lifecycle status: disconnect keeps them (a
    reconnect resumes the assignment) and Project deactivation keeps them
    (catalog queries filter ``projects.is_active`` themselves). Only actual
    row deletion cascades.

    The bot-turn runtime reads this table through
    :meth:`RetrievalRepository.page_project_ids`; admin editing goes through
    the Page↔Project CRUD endpoints in ``app/api/integrations.py``.
    """

    __tablename__ = "channel_account_projects"

    channel_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
