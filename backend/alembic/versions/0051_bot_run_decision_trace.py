"""Add bounded decision-trace storage to bot runs.

Revision ID: 0051_bot_run_decision_trace
Revises: 0050_data_ingestion_recovery
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0051_bot_run_decision_trace"
down_revision = "0050_data_ingestion_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_runs",
        sa.Column("decision_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_runs", "decision_trace")
