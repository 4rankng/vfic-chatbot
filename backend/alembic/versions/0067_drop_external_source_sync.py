"""drop external-source sync state — Google Sheets are retired

Removes the two sync-control tables behind the retired Google Sheet feature
(the console surface was removed earlier; this is the server half). The owner
ruled the feature dead on 2026-10-05. Rows were the only record of a linked
sheet; the published category revisions/chunks they once fed are NOT touched —
``last_revision_id`` never had an FK precisely so published content would
survive row deletion, and the drop honours that.

DATA WARNING: upgrade() drops both tables WITH their rows. Back the database
up before this migration first runs (pg_dump before ``make deploy``).

``downgrade()`` recreates both tables EMPTY (the exact 0052/0053 column sets)
so a rollback deploy never hits missing-table errors; it cannot restore the
dropped rows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0067_drop_external_source_sync"
down_revision = "0066_drop_persona_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_external_source_sync_state_auto_sync_enabled",
        table_name="external_source_sync_state",
    )
    op.drop_table("external_source_sync_state")
    op.drop_index(
        "ix_single_page_external_source_sync_state_auto_sync_enabled",
        table_name="single_page_external_source_sync_state",
    )
    op.drop_table("single_page_external_source_sync_state")


def downgrade() -> None:
    op.create_table(
        "external_source_sync_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
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
    op.create_index(
        "ix_external_source_sync_state_auto_sync_enabled",
        "external_source_sync_state",
        ["auto_sync_enabled"],
        postgresql_where=sa.text("auto_sync_enabled = true"),
    )
    op.create_table(
        "single_page_external_source_sync_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'google_sheet'"),
        ),
        sa.Column("sheet_url", sa.String(length=512), nullable=False),
        sa.Column("sheet_gid", sa.BigInteger(), nullable=False),
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
            "source_kind",
            name="uq_single_page_external_source_per_project_source",
        ),
    )
    op.create_index(
        "ix_single_page_external_source_sync_state_auto_sync_enabled",
        "single_page_external_source_sync_state",
        ["auto_sync_enabled"],
        postgresql_where=sa.text("auto_sync_enabled = true"),
    )
