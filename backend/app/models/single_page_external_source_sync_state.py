"""Single-page external-source sync state.

One row per ``(project, source)`` tracks the last import of a public Google
Sheet into a DIRECT_CONTEXT project's live single-page file. The shape mirrors
``external_source_sync_state`` closely so operational handling (status, retries,
auto-disable) stays familiar, while remaining additive and isolated from the
RAG category sync path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SinglePageExternalSourceSyncState(Base):
    """Per-``(project, source)`` single-page external-sync tracking row."""

    __tablename__ = "single_page_external_source_sync_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="google_sheet", server_default="google_sheet"
    )
    sheet_url: Mapped[str] = mapped_column(String(512), nullable=False)
    sheet_gid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    auto_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_content_hash: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="NEW", server_default="NEW"
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_row_count: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_kind",
            name="uq_single_page_external_source_per_project_source",
        ),
    )
