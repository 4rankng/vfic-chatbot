"""Require an exact successful preview before template publication."""

from alembic import op
import sqlalchemy as sa


revision = "0040_template_preview_gate"
down_revision = "0039_multi_vertical_ingestion_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_template_versions", sa.Column("preview_checksum", sa.String(64), nullable=True))
    op.add_column("ingestion_template_versions", sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_template_versions", "previewed_at")
    op.drop_column("ingestion_template_versions", "preview_checksum")
