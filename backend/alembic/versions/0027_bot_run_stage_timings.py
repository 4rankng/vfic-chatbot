"""bot_run stage timings

Revision ID: 0027_bot_run_stage_timings
Revises: 0026_faq_bypass_rule_terms
Create Date: 2026-07-09

Adds a nullable ``stage_timings`` JSONB column to ``bot_runs``. Each turn
records per-stage wall-clock (ms) captured by ``app.graph.runner.run_turn``:
``webhook_to_pickup_ms`` / ``preamble_ms`` / ``lane`` / ``lead_ms`` /
``llm_ms`` / ``safety_ms`` / ``send_ms`` / ``total_ms`` (+ ``queue_depth``).
The performance dashboard aggregates these with ``percentile_cont``.

Additive only — no backfill (older runs keep NULL and are excluded from
percentiles), no index (low-volume table; the existing started_at indexes
bound the time-window scans).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027_bot_run_stage_timings"
down_revision: Union[str, None] = "0026_faq_bypass_rule_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS stage_timings jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bot_runs DROP COLUMN IF EXISTS stage_timings")
