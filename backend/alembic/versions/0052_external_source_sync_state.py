"""Add per-(project, category, source) external knowledge-source sync state.

Revision ID: 0052_external_source_sync_state
Revises: 0051_bot_run_decision_trace

Tracks the last import of a public Google Sheet (today) into a project-owned RAG
category. Category-agnostic by design — the same row shape covers ``faq`` now and
``transportation`` / ``compensation`` / any other category later, so no further
sync-state migrations are expected.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0052_external_source_sync_state"
down_revision = "0051_bot_run_decision_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_source_sync_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Stored lowercase ("faq", "transportation") so KnowledgeCategoryKey(value)
        # construction never trips the uppercase casing gap.
        sa.Column("category_key", sa.String(length=32), nullable=False),
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'google_sheet'"),
        ),
        sa.Column("sheet_url", sa.String(length=512), nullable=False),
        sa.Column("sheet_gid", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "auto_sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_content_hash", sa.String(length=64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_status", sa.String(length=16), nullable=False, server_default=sa.text("'NEW'")
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_row_count", sa.Integer(), nullable=True),
        # INTENTIONALLY NO foreign key: knowledge_documents.category_revision_id
        # and knowledge_chunks.category_revision_id ARE ondelete=CASCADE, so an FK
        # here would turn admin "Remove source" into wholesale published-FAQ
        # deletion. See tests/test_external_source_sync_api.py
        # ::test_delete_does_not_delete_published_chunks.
        sa.Column("last_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "project_id",
            "category_key",
            "source_kind",
            name="uq_external_source_per_project_category_source",
        ),
    )
    # The daily tick scans WHERE auto_sync_enabled = TRUE; a partial index keeps
    # that scan over a tiny set even as dormant rows accumulate.
    op.create_index(
        "ix_external_source_sync_state_auto_sync_enabled",
        "external_source_sync_state",
        ["auto_sync_enabled"],
        postgresql_where=sa.text("auto_sync_enabled = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_source_sync_state_auto_sync_enabled",
        table_name="external_source_sync_state",
    )
    op.drop_table("external_source_sync_state")
