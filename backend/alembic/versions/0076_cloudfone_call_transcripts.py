"""cloudfone_call_transcripts — one row per transcribed call.

Additive: a new table, no existing row is touched, so blue/green runs either
way. ``downgrade()`` drops it (a later pass re-downloads and re-transcribes any
call still in the vendor's history window).
"""

from alembic import op
import sqlalchemy as sa


revision = "0076_cloudfone_call_transcripts"
down_revision = "0075_channel_account_bot_pause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloudfone_call_transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("started_at", sa.String(length=40), nullable=False),
        sa.Column("caller", sa.String(length=64), nullable=False),
        sa.Column("talk_seconds", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", name="cloudfone_call_transcripts_call_id_key"),
    )
    op.create_index(
        "ix_cloudfone_call_transcripts_day",
        "cloudfone_call_transcripts",
        ["day"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cloudfone_call_transcripts_day", table_name="cloudfone_call_transcripts"
    )
    op.drop_table("cloudfone_call_transcripts")
