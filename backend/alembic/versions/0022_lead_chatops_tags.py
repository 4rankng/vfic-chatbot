"""Add persistent ChatOps lead tags.

Revision ID: 0022_lead_chatops_tags
Revises: 0021_zalo_channels_settings
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_lead_chatops_tags"
down_revision = "0021_zalo_channels_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_tags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False, server_default="info"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "key", name="uq_lead_tags_lead_key"),
        schema="public",
    )
    op.create_index("ix_lead_tags_lead_id", "lead_tags", ["lead_id"], schema="public")
    op.create_index("ix_lead_tags_key", "lead_tags", ["key"], schema="public")


def downgrade() -> None:
    op.drop_index("ix_lead_tags_key", table_name="lead_tags", schema="public")
    op.drop_index("ix_lead_tags_lead_id", table_name="lead_tags", schema="public")
    op.drop_table("lead_tags", schema="public")
