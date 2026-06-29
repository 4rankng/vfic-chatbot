"""Proactive follow-up columns on conversations + partial eligibility index.

Adds the state needed for the bot to proactively nudge interested-but-silent leads:
- followup_count: successful proactive sends so far (hard cap per lead).
- last_followup_at: timestamp of last successful proactive send.
- last_followup_attempt_at: timestamp of last attempt (success or failure), for
  backoff cooldown on failed Zalo sends.
- followup_opted_out: one-way hard stop (keyword / silence / recruiter set).

The partial index covers the eligibility scan (BOT + OPEN + not opted-out) and is
ordered by last_inbound_at DESC so the 48h-window filter runs on the hottest rows first.

Proactive BOT messages are identified by sender='BOT' AND bot_run_id IS NULL
(proactive turns deliberately log no BotRun).

Revision ID: 0013_proactive_followup
Revises: 0013_password_reset_otps
Create Date: 2026-06-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_proactive_followup"
down_revision = "0013_password_reset_otps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("followup_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("conversations", sa.Column("last_followup_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("last_followup_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("followup_opted_out", sa.Boolean(), nullable=False, server_default="false"))

    op.create_index(
        "conversations_followup_candidate_idx",
        "conversations",
        ["last_inbound_at"],
        postgresql_where="mode='BOT' AND status='OPEN' AND followup_opted_out=FALSE",
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("conversations_followup_candidate_idx", table_name="conversations")
    op.drop_column("conversations", "followup_opted_out")
    op.drop_column("conversations", "last_followup_attempt_at")
    op.drop_column("conversations", "last_followup_at")
    op.drop_column("conversations", "followup_count")
