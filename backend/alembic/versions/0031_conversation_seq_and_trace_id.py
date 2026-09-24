"""Add conversation_seq + bot_runs.trace_id for end-to-end tracing.

Revision ID: 0031_conversation_seq_trace
Revises: 0030_send_unknown
Create Date: 2026-07-12

Two additive columns, both for observability only (no behavior change):

1. ``conversations.conversation_seq`` (BigInteger) — a strict monotonic per-
   conversation counter that increments on EVERY mutation, including bot
   outcomes and receipts (unlike ``conversations.version``, which intentionally
   skips bot outcomes to avoid invalidating in-flight optimistic-lock guards).
   Used to answer "did message B process before A?" without ambiguity.
   Backfilled from ``version`` as a starting approximation (version skips bot
   outcomes, so the backfill is a lower bound — acceptable for a debugging aid).

2. ``bot_runs.trace_id`` (String(36)) — the webhook request_id propagated through
   the RQ job dict and BotRunState, so one ``trace_id`` query returns every log
   line for a single candidate message's journey (webhook → RQ → LangGraph →
   Zalo send). Indexed for log-correlation queries.

Reversible — both columns and the index are cleanly droppable.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031_conversation_seq_trace"
down_revision: Union[str, None] = "0030_send_unknown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS conversation_seq BIGINT "
        "NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE bot_runs "
        "ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36)"
    )
    # Backfill seq from version as a reasonable starting point (approximate —
    # version skips bot outcomes, but this is a debugging aid, not a correctness
    # mechanism). Only bump rows where the default 1 would understate history.
    op.execute(
        "UPDATE conversations SET conversation_seq = version "
        "WHERE conversation_seq = 1 AND version > 1"
    )
    # bot_runs is an existing table with live rows: CREATE INDEX would take a
    # write-blocking lock for the whole build, queueing candidate writes while
    # the old colour still serves (migrations run mid-deploy). CONCURRENTLY
    # needs no surrounding transaction — same pattern as 0014/0016.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_bot_runs_trace_id "
            "ON bot_runs (trace_id)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bot_runs_trace_id")
    op.execute("ALTER TABLE bot_runs DROP COLUMN IF EXISTS trace_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS conversation_seq")
