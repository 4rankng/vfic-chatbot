"""Add DELIVERED/READ values to the delivery_status enum.

Revision ID: 0024_delivery_read_states
Revises: 0023_kb_versioned_ingestion
Create Date: 2026-07-08

Tracks Zalo OA delivery/read receipts against outbound messages. Postgres
``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction, so each statement
runs in an autocommit block. The change is idempotent (``IF NOT EXISTS``); the
downgrade is a no-op because ``ADD VALUE`` is irreversible (the new values are
simply unused if the application rolls back).
"""

from alembic import op

revision = "0024_delivery_read_states"
down_revision = "0023_kb_versioned_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE delivery_status ADD VALUE IF NOT EXISTS 'DELIVERED'")
        op.execute("ALTER TYPE delivery_status ADD VALUE IF NOT EXISTS 'READ'")


def downgrade() -> None:
    # downgrade: INTENTIONAL_NOOP — ALTER TYPE ... ADD VALUE is not reversible
    # (PostgreSQL cannot drop an enum value); the values are inert unless the
    # receipt-handling code path writes them.
    pass
