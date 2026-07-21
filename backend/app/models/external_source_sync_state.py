"""External knowledge-source sync state.

One row per ``(project, category, source)`` tracks the last import of an
external sheet (public Google Sheet today, other public-link sources tomorrow)
into a project-owned RAG category. Designed from day one to be category-agnostic
— the same row shape covers ``faq`` now and ``transportation`` / ``compensation``
/ any other :class:`~app.schemas.knowledge_categories.KnowledgeCategoryKey`
later, with no new tables.

The ``last_content_hash`` enables a skip-if-unchanged optimisation: it is keyed
on the active category revision's ``content_sha256`` (see the orchestrator), so a
no-op daily tick costs one CSV fetch + one hash compare and stages nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExternalSourceSyncState(Base):
    """Per-``(project, category, source)`` external-sync tracking row."""

    __tablename__ = "external_source_sync_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Stored lowercase ("faq", "transportation"). Normalise .lower() on write so
    # KnowledgeCategoryKey(value) construction never trips the uppercase casing gap.
    category_key: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="google_sheet", server_default="google_sheet"
    )
    # Validated against the host allow-list at API entry; never trusted at fetch
    # time (the SSRF gate reconstructs the export URL from the parsed sheet id).
    sheet_url: Mapped[str] = mapped_column(String(512), nullable=False)
    sheet_gid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    auto_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 3-strike auto-disable: consecutive FAILED syncs with a revocable reason
    # (sheet_not_public / http_401 / http_403 / http_404 / http_410 /
    # dns_resolution_failed) flip auto_sync_enabled to False. Reset to 0 on any
    # non-FAILED outcome. Transient failures (network blip, 500) do not count.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Keyed on revision.content_sha256 (not parser output) so a partial-activation
    # rollback cannot leave last_content_hash pointing at content that never went live.
    last_content_hash: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NEW | OK | NO_OP | FAILED
    last_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="NEW", server_default="NEW"
    )
    # Sanitised: short error code + de-headed message (URLs/query strings stripped),
    # capped at 500 chars. Never stores raw str(exc) from httpx.
    last_error: Mapped[str | None] = mapped_column(Text)
    last_row_count: Mapped[int | None] = mapped_column(Integer)
    # INTENTIONALLY NO ForeignKey. KnowledgeDocument.category_revision_id and
    # KnowledgeChunk.category_revision_id ARE ondelete=CASCADE — so adding
    # ``ForeignKey(..., ondelete="CASCADE")`` here would silently turn an admin
    # "Remove source" click into wholesale published-FAQ deletion. Never add this
    # FK without revisiting tests/test_external_source_sync_api.py
    # ::test_delete_does_not_delete_published_chunks.
    last_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
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
            "category_key",
            "source_kind",
            name="uq_external_source_per_project_category_source",
        ),
    )
