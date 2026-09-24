"""merge 0013_password_reset_otps + 0013_proactive_followup

Revision ID: 091e7edc9f76
Revises: 0013_password_reset_otps, 0013_proactive_followup
Create Date: 2026-06-29 15:45:58.608944

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "091e7edc9f76"
down_revision: Union[str, None] = ("0013_password_reset_otps", "0013_proactive_followup")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge nodes carry no DDL by design: this revision only joins the two
    # 0013_ branches back into a single head for Alembic's graph.
    pass


def downgrade() -> None:
    # downgrade: INTENTIONAL_NOOP — a merge node has no DDL to reverse;
    # downgrading past it means taking one of the merged branches explicitly.
    pass
