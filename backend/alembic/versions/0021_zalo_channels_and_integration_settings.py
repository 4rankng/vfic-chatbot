"""Add Zalo channel metadata and integration settings.

Revision ID: 0021_zalo_channels_and_integration_settings
Revises: 0020_persona_followup_rules
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0021_zalo_channels_and_integration_settings"
down_revision = "0020_persona_followup_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "zalo_channel",
            sa.String(),
            nullable=False,
            server_default=sa.text("'bot'"),
        ),
        schema="public",
    )
    op.create_index(
        "ix_conversations_zalo_channel",
        "conversations",
        ["zalo_channel"],
        schema="public",
    )
    op.create_table(
        "integration_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
        schema="public",
    )
    op.execute(
        """
        CREATE TRIGGER touch_integration_settings_updated_at
        BEFORE UPDATE ON public.integration_settings
        FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS touch_integration_settings_updated_at "
        "ON public.integration_settings"
    )
    op.drop_table("integration_settings", schema="public")
    op.drop_index("ix_conversations_zalo_channel", table_name="conversations", schema="public")
    op.drop_column("conversations", "zalo_channel", schema="public")
