"""Per-Page bot pause: keep receiving candidate messages, stop auto-replies.

The Messenger settings page gains a "pause the bot" switch per connected Page.
Paused means exactly: webhooks are still accepted and every candidate message
is still persisted (the console keeps the full thread for manual replies), but
no bot turn is enqueued or sent on that Page — the three hook points are the
inbound scheduler (no enqueue), the reconcile sweep (no recovery turn), and a
run_turn backstop (a job enqueued before the flip suppresses itself instead of
sending). Not to be confused with the account lifecycle: the Page stays ACTIVE
and fully connected; only the bot's replies rest.

Revision ID: 0075_channel_account_bot_pause
Revises: 0074_map_lg_ads_album_tuoi
"""

from alembic import op
import sqlalchemy as sa

revision = "0075_channel_account_bot_pause"
down_revision = "0074_map_lg_ads_album_tuoi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_accounts",
        sa.Column(
            "bot_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_accounts", "bot_paused")
