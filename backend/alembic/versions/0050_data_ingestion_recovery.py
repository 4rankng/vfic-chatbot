"""Add recoverable category processing and explicit cutover state.

Revision ID: 0050_data_ingestion_recovery
Revises: 0049_adapter_persona_assignments
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0050_data_ingestion_recovery"
down_revision = "0049_adapter_persona_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_category_revisions",
        sa.Column("processing_token", sa.UUID(), nullable=True),
    )
    op.add_column(
        "knowledge_category_revisions",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_category_revisions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_category_revisions",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_category_revisions",
        sa.Column("failure_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_category_revisions",
        sa.Column(
            "quality_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_knowledge_category_revision_lease",
        "knowledge_category_revisions",
        ["status", "lease_expires_at"],
    )
    op.add_column(
        "projects",
        sa.Column(
            "category_cutover_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("category_cutover_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "category_cutover_at")
    op.drop_column("projects", "category_cutover_snapshot")
    op.drop_index(
        "ix_knowledge_category_revision_lease",
        table_name="knowledge_category_revisions",
    )
    op.drop_column("knowledge_category_revisions", "quality_result")
    op.drop_column("knowledge_category_revisions", "failure_code")
    op.drop_column("knowledge_category_revisions", "attempt_count")
    op.drop_column("knowledge_category_revisions", "lease_expires_at")
    op.drop_column("knowledge_category_revisions", "processing_started_at")
    op.drop_column("knowledge_category_revisions", "processing_token")
