"""bot_runs.started_at standalone index for the performance dashboard.

Revision ID: 0032_bot_runs_started_at_index
Revises: 0031_conversation_seq_and_trace_id
Create Date: 2026-07-12

Adds ``bot_runs_started_at_idx`` on ``(started_at DESC)`` so the five dashboard
queries in ``app/api/performance.py`` (``_percentiles``, ``_lane_outcome_counts``,
``_slow_turns``, ``_trend``, ``_reliability``) stop sequential-scanning the whole
table on every ``GET /admin/performance`` call. All five filter
``WHERE started_at >= now() - (:interval)::interval`` but none constrain the
leading column of the existing composite indexes —
``bot_runs_conv_idx (conversation_id, started_at DESC)`` and
``bot_runs_outcome_started_at_idx (outcome, started_at DESC)`` — so Postgres
falls back to a full table scan today.

Corrects a stale comment in ``0027_bot_run_stage_timings.py``, which claimed
"the existing started_at indexes bound the time-window scans." That is wrong:
both pre-existing indexes have a non-``started_at`` leading column, so neither
can bound a ``started_at``-only range predicate. This migration adds the
standalone index that 0027 mistakenly believed already existed.

``DESC`` matches the natural "most recent first" access pattern and the
convention used by the two composite indexes above. Built ``CONCURRENTLY`` so
there is no write lock on the live table; reversible via
``DROP INDEX CONCURRENTLY``.

Reversible — the index is cleanly droppable.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032_bot_runs_started_at_index"
down_revision: Union[str, None] = "0031_conversation_seq_and_trace_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction; mirror the
    # 0016_query_perf_indexes pattern with autocommit_block().
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS bot_runs_started_at_idx
              ON public.bot_runs (started_at DESC);
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.bot_runs_started_at_idx")
