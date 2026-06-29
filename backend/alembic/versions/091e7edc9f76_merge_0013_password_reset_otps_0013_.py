"""merge 0013_password_reset_otps + 0013_proactive_followup

Revision ID: 091e7edc9f76
Revises: 0013_password_reset_otps, 0013_proactive_followup
Create Date: 2026-06-29 15:45:58.608944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '091e7edc9f76'
down_revision: Union[str, None] = ('0013_password_reset_otps', '0013_proactive_followup')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
