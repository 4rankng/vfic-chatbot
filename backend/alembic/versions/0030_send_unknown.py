"""Add SEND_UNKNOWN value to the delivery_status enum.

Revision ID: 0030_send_unknown
Revises: 0029_delivery_status_sending
Create Date: 2026-07-12

Distinguishes ambiguous send outcomes (transport timeout / reset after the request
may have reached Zalo) from definite failures. Without this, a transport timeout
becomes FAILED → the reconcile sweep re-enqueues the whole turn → the LLM
regenerates → the candidate receives a duplicate reply. SEND_UNKNOWN is
non-retriable: the reconciler skips these rows and surfaces them for manual review
instead of blindly re-running.

Like 0029 (SENDING), Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a
transaction, so it runs in an autocommit block. Idempotent (``IF NOT EXISTS``); the
downgrade is a no-op because ``ADD VALUE`` is irreversible (the value is simply
unused if the application rolls back).
"""

from alembic import op

revision = "0030_send_unknown"
down_revision = "0029_delivery_status_sending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE delivery_status ADD VALUE IF NOT EXISTS 'SEND_UNKNOWN'")


def downgrade() -> None:
    # downgrade: INTENTIONAL_NOOP — ALTER TYPE ... ADD VALUE is not reversible
    # (PostgreSQL cannot drop an enum value); the value is inert unless the
    # send-failure classifier code path writes it.
    pass
