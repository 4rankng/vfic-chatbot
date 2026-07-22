"""Add direct-context single-page external source sync state.

Revision ID: 0053_single_page_external_source_sync_state
Revises: 0052_external_source_sync_state
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0053_single_page_external_source_sync_state"
down_revision = "0052_external_source_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(
        "ix_single_page_external_source_sync_state_auto_sync_enabled",
        table_name="single_page_external_source_sync_state",
    )
    op.drop_table("single_page_external_source_sync_state")
