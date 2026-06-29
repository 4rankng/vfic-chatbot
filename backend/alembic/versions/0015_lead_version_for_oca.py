"""Add ``version`` column to leads for optimistic concurrency control.

Recruiter-vs-recruiter lead edit race: a recruiter loads a lead at version N,
another recruiter updates it (version becomes N+1), the first recruiter's
update now checks ``WHERE version = N`` and fails with rowcount == 0 → 409.

Revision ID: 0015_lead_version_for_oca
Revises: 0014_retrieval_scaling_indexes
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_lead_version_for_oca"
down_revision = "0014_retrieval_scaling_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("leads", "version")
