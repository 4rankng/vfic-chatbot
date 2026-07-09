"""Add SENDING value to the delivery_status enum.

Revision ID: 0029_delivery_status_sending
Revises: 0028_bot_lock_owner
Create Date: 2026-07-09

Outbound idempotency: a bot reply is flipped PENDING -> SENDING by an atomic
conditional claim immediately before the Zalo POST. If a worker crashes between
the send and the SENT write, the reconcile sweep recognizes the stale SENDING
row as sent-but-unconfirmed (at-most-once) instead of re-enqueuing a duplicate
reply. Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction, so
it runs in an autocommit block. Idempotent (``IF NOT EXISTS``); the downgrade is
a no-op because ``ADD VALUE`` is irreversible (the value is simply unused if the
application rolls back).
"""

from alembic import op

revision = "0029_delivery_status_sending"
down_revision = "0028_bot_lock_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE delivery_status ADD VALUE IF NOT EXISTS 'SENDING'")


def downgrade() -> None:
    # ALTER TYPE ... ADD VALUE is not reversible; leaving the value in place is
    # safe because it is only written by the outbound-claim code path.
    pass
