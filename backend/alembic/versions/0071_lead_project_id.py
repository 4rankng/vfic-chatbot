"""leads.project_id — the dự án a candidate was recruited for.

Project interest was durable but only in ``lead_events.payload`` (event_type
``project_interest``), so the recruiter console's lead list and any export had
no way to filter by project without an unindexed join over the JSONB event
table. This migration gives the lead row its own pointer to the catalog entry
the candidate entered through.

Additive: a nullable column, so blue/green runs either way and no existing row
is touched. It is DERIVED state — written from the same seam that writes the
``project_interest`` event, first-touch-wins — and is fully rebuildable from
that event, which is why the backfill is deliberately absent here: existing
rows can be backfilled from ``lead_events`` under operator approval, and a
migration that rewrote every lead row would not be blue/green-safe.

``ondelete=SET NULL`` (not CASCADE): retiring a project from the catalog must
never delete the candidate who came from its ad. The interest event row is the
audit trail and survives independently.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0071_lead_project_id"
down_revision = "0070_backfill_lead_age_from_birth_year"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_leads_project_id", "leads", ["project_id"])
    op.create_foreign_key(
        "fk_leads_project_id",
        "leads",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_leads_project_id", "leads", type_="foreignkey")
    op.drop_index("ix_leads_project_id", table_name="leads")
    op.drop_column("leads", "project_id")
