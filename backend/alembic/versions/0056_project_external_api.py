"""Add the per-project external API integration column.

One nullable JSONB column on ``projects`` holding the admin-managed external API
integration (base URL, auth header/scheme, the AES-GCM sealed API key, and the
endpoint catalog the bot may call). Additive and reversible: no backfill, no
constraint, and the reader treats NULL exactly like a disabled config.

Revision ID: 0056_project_external_api
Revises: 0055_memories_match_halfvec
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0056_project_external_api"
down_revision = "0055_memories_match_halfvec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("external_api", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "external_api")
