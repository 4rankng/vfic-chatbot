"""Add per-Agent proactive follow-up rules.

Revision ID: 0020_persona_followup_rules
Revises: 0019_drop_lead_latest_company
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020_persona_followup_rules"
down_revision = "0019_drop_lead_latest_company"
branch_labels = None
depends_on = None


DEFAULT_FOLLOWUP_RULES = {
    "hot": {
        "enabled": True,
        "cadence_hours": [10, 22, 46],
        "eligible_stages": ["NEW"],
    },
    "warm": {
        "enabled": True,
        "cadence_hours": [22, 46],
        "eligible_stages": ["NEW"],
    },
    "not_interested": {
        "enabled": True,
        "cadence_hours": [46],
        "eligible_stages": ["NEW"],
    },
}


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column(
            "followup_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                """'{"hot":{"enabled":true,"cadence_hours":[10,22,46],"eligible_stages":["NEW"]},"warm":{"enabled":true,"cadence_hours":[22,46],"eligible_stages":["NEW"]},"not_interested":{"enabled":true,"cadence_hours":[46],"eligible_stages":["NEW"]}}'::jsonb"""
            ),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("personas", "followup_rules", schema="public")
