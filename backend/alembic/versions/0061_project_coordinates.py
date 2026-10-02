"""Persist a project's work address and its coordinates.

``projects.latitude``/``longitude``/``extracted_address`` let the catalog tool
compute "how far is this dự án from the candidate" instead of only matching
location tokens. All three are nullable and additive: a project whose brief
states no work address (or whose address cannot be geocoded) keeps NULL and
behaves exactly as before — no backfill, no constraint, no default.

``extracted_address`` stores the verbatim work address the LLM extracted from
the uploaded brief (grounded against that brief), which is also the cache that
stops a re-ingest from re-running the extraction.

Revision ID: 0061_project_coordinates
Revises: 0060_drop_bot_run_decision_trace
"""

from alembic import op
import sqlalchemy as sa


revision = "0061_project_coordinates"
down_revision = "0060_drop_bot_run_decision_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("extracted_address", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "extracted_address")
    op.drop_column("projects", "longitude")
    op.drop_column("projects", "latitude")
