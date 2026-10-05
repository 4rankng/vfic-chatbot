"""push_subscriptions — one row per browser a user enabled push on.

Additive: a new table, no existing row is touched, so blue/green runs either way.
``downgrade()`` drops it (subscriptions are re-created by the console toggle, so
nothing is lost that the operator cannot redo in one click).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0068_push_subscriptions"
down_revision = "0067_drop_external_source_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("failure_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="push_subscriptions_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="push_subscriptions_pkey"),
        sa.UniqueConstraint("endpoint", name="push_subscriptions_endpoint_key"),
    )
    # Fan-out reads every subscription of a user (and of every admin) by user id.
    op.create_index(
        "push_subscriptions_user_id_idx", "push_subscriptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("push_subscriptions_user_id_idx", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
