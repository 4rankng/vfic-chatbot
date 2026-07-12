"""Widen the messages delivery partial index to cover SEND_UNKNOWN.

Revision ID: 0034_messages_delivery_review_index
Revises: 0033_bot_runs_started_at_index
Create Date: 2026-07-12

The recruiter attention dashboard's DELIVERY_REVIEW reason surfaces
conversations whose latest outbound (BOT/RECRUITER) message is in a delivery
state that needs manual review: ``FAILED`` (reconciled failure) and
``SEND_UNKNOWN`` (transport timeout/reset — intentionally non-reconciled per
``reconcile_worker.py``, surfaced for manual confirm/cancel).

The existing partial index added in ``0016_query_perf_indexes.py`` covers only
``WHERE delivery_status = 'FAILED'``. The dashboard predicate is
``delivery_status IN ('FAILED','SEND_UNKNOWN')``, so SEND_UNKNOWN rows would
sequential-scan the append-only ``messages`` table on every dashboard read.

This migration widens that partial index by dropping the FAILED-only index and
creating ``messages_delivery_review_idx`` with the predicate
``WHERE delivery_status IN ('FAILED','SEND_UNKNOWN')``. The new index is a
strict superset of the old (every FAILED row is still indexed) plus the
SEND_UNKNOWN rows, so the existing ``count_failed_sends`` dashboard counter
remains index-backed.

Both statements run ``CONCURRENTLY`` inside ``autocommit_block()`` (mirrors
0014/0016) because ``CREATE/DROP INDEX CONCURRENTLY`` cannot execute inside a
transaction. Fully reversible: the downgrade restores the original FAILED-only
partial index.

Human-approved per AGENTS.md §13 (additive migration on a protected path).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0034_messages_delivery_review_index"
down_revision = "0033_bot_runs_started_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP the old FAILED-only partial index, then CREATE the widened partial
    # index in the same autocommit_block. CONCURRENTLY forbids running inside a
    # transaction; autocommit_block() commits the outer transaction so each
    # statement runs standalone. IF EXISTS / IF NOT EXISTS keep it idempotent.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.messages_delivery_status_failed_idx")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_delivery_review_idx
              ON public.messages (delivery_status)
              WHERE delivery_status IN ('FAILED','SEND_UNKNOWN');
            """
        )


def downgrade() -> None:
    # Reverse of upgrade: drop the widened index and restore the original
    # FAILED-only partial index from 0016.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.messages_delivery_review_idx")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_delivery_status_failed_idx
              ON public.messages (delivery_status)
              WHERE delivery_status = 'FAILED';
            """
        )
