"""Drop the per-run decision-trace column.

The decision-trace feature (bounded per-turn agent thinking log) was removed
end to end: nothing writes or reads ``bot_runs.decision_trace`` any more. The
original column was added by ``0051_bot_run_decision_trace``; this revision
drops it while keeping the historical chain linear.

Revision ID: 0060_drop_bot_run_decision_trace
Revises: 0059_category_markdown_source
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0060_drop_bot_run_decision_trace"
down_revision = "0059_category_markdown_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("bot_runs", "decision_trace")


def downgrade() -> None:
    op.add_column(
        "bot_runs",
        sa.Column("decision_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
