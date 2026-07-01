"""Add per-Agent proactive follow-up rules.

Revision ID: 0020_persona_followup_rules
Revises: 0019_drop_lead_latest_company
Create Date: 2026-07-01
"""

import json

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


def _safe_json_server_default(data: dict) -> str:
    """Escape JSON primitives that look like identifiers to prevent
    SQLAlchemy text() from treating them as bound parameters.

    sa.text() interprets ``:word`` as a named bind parameter.  JSON
    booleans/null (true/false/null) match that pattern, so colons
    preceding them must be backslash-escaped.
    """
    raw = json.dumps(data, separators=(",", ":"))
    return raw.replace(":true", "\\:true").replace(":false", "\\:false").replace(":null", "\\:null")


def upgrade() -> None:
    default = _safe_json_server_default(DEFAULT_FOLLOWUP_RULES)
    op.add_column(
        "personas",
        sa.Column(
            "followup_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{default}'::jsonb"),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("personas", "followup_rules", schema="public")
