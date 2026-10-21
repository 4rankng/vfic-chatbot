"""cloudfone_transcript_days — one row per inspected Cloudfone call day.

The daily insights pass and the on-demand viewer backfill both write this
marker. A day with a marker was already fetched from Cloudfone, so the viewer
knows the day is known (and possibly empty) instead of fetching it again. A day
without a marker was never inspected — that is what lets the admin viewer pull
a day on demand.

Additive: a new table, no existing row is touched, so blue/green runs either
way. ``downgrade()`` drops it (every day then reads as never inspected, so the
viewer fetches on demand again).
"""

from alembic import op
import sqlalchemy as sa


revision = "0077_cloudfone_transcript_days"
down_revision = "0076_cloudfone_call_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloudfone_transcript_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("call_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "recordable_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "transcript_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("cloudfone_transcript_days")
