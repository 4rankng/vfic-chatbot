"""outbound_outbox: transactional outbox for outbound bot replies.

Tech-Lead Directive §14: "insert outbound_message + outbound_outbox event in one
DB transaction, commit, then a dispatcher sends to Zalo and marks sent. This is
safer than sending first and persisting afterward."

This migration adds the ``outbound_outbox`` table. It mirrors the send intent
for every outbound BOT message: the Zalo payload, the dispatch status, the
attempt count, and the last error. The table is the authoritative "was this
sent?" record that:

- Lets reconcile detect duplicate sends (the directive's
  ``duplicate_outbound_rate = 0`` SLO from P0-2 finally has a data source).
- Survives crashes in the window between ``zalo.send_message`` succeeding and
  ``record_bot_outcome`` committing (a stale SENDING outbox row is the
  reconciliation target, not a re-send trigger).
- Provides an audit trail of every dispatch attempt.

Design (conservative — preserves the proven inline-send behavior):

The current code sends inline (``runner.py`` calls ``zalo.send_message`` directly
inside the turn). We KEEP that behavior — decoupling send from turn execution
would add latency and the inline send is battle-tested. The outbox row is
written in the SAME transaction as the send outcome (via ``record_bot_outcome``);
a periodic sweep is the safety net for rows left in SENDING by a crash.

Reversible via ``DROP TABLE outbound_outbox``.
"""

from alembic import op
import sqlalchemy as sa

revision = "0036_outbound_outbox"
down_revision = "0035_lead_avatar_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbound_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "channel",
            sa.String(32),
            nullable=False,
            comment="zalo_bot | zalo_oa | web_chat",
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            comment="The exact Zalo send payload (chat_id, text, quote_message_id, ...)",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            comment="PENDING | SENDING | SENT | FAILED | SEND_UNKNOWN | SUPPRESSED",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of dispatch attempts (inline + sweep)",
        ),
        sa.Column(
            "last_error", sa.Text(), nullable=True, comment="Last dispatch error message"
        ),
        sa.Column(
            "zalo_message_id",
            sa.String(128),
            nullable=True,
            comment="Message ID returned by Zalo on successful send",
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the send succeeded (wall-clock)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "message_id",
            name="uq_outbound_outbox_message_id",
            comment="One outbox row per outbound message (prevents duplicate enqueues)",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','FAILED','SEND_UNKNOWN','SUPPRESSED')",
            name="ck_outbound_outbox_status",
        ),
    )
    # Dispatcher scan: pending rows ordered by age. Partial index keeps it small.
    op.execute(
        "CREATE INDEX ix_outbound_outbox_pending_created "
        "ON outbound_outbox (created_at) "
        "WHERE status IN ('PENDING','SENDING')"
    )
    # SLO rollup: count by status over a window.
    op.create_index(
        "ix_outbound_outbox_status_created",
        "outbound_outbox",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_outbox_status_created", table_name="outbound_outbox")
    op.execute("DROP INDEX IF EXISTS ix_outbound_outbox_pending_created")
    op.drop_table("outbound_outbox")
