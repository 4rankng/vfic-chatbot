"""Drop unused lead latest_company field.

Revision ID: 0019_drop_lead_latest_company
Revises: 0018_backfill_conversation_leads
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_drop_lead_latest_company"
down_revision = "0018_backfill_conversation_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("leads", "latest_company", schema="public")


def downgrade() -> None:
    op.add_column("leads", sa.Column("latest_company", sa.Text(), nullable=True), schema="public")
