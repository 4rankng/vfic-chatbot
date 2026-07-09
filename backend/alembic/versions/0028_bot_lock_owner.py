"""bot lock owner token

Revision ID: 0028_bot_lock_owner
Revises: 0027_bot_run_stage_timings
Create Date: 2026-07-09

Adds an owner token and heartbeat timestamp to the per-conversation bot lock.
The lock TTL remains the recovery mechanism, while the owner token lets stale
jobs prove they still own the lock before sending or clearing it.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028_bot_lock_owner"
down_revision: Union[str, None] = "0027_bot_run_stage_timings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
          ADD COLUMN IF NOT EXISTS bot_lock_owner uuid,
          ADD COLUMN IF NOT EXISTS bot_lock_heartbeat_at timestamptz
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
          DROP COLUMN IF EXISTS bot_lock_heartbeat_at,
          DROP COLUMN IF EXISTS bot_lock_owner
        """
    )
