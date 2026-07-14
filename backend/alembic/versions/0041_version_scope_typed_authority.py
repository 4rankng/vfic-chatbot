"""Scope extracted recruitment authority rows to a KB release.

Legacy rows stay nullable and remain readable only as a compatibility fallback.
New writer paths can bind facts to one immutable KB release so activation and
rollback cannot combine old chunks with a newer structured row.
"""

from alembic import op
import sqlalchemy as sa


revision = "0041_version_scope_typed_authority"
down_revision = "0040_template_preview_gate"
branch_labels = None
depends_on = None


_TABLES = ("faq_entry", "job_requirement", "job_benefit", "job_shift", "job_location", "working_hours")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("kb_version_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_kb_version",
            table,
            "kb_versions",
            ["kb_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_kb_version", table, ["kb_version_id"])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_kb_version", table_name=table)
        op.drop_constraint(f"fk_{table}_kb_version", table, type_="foreignkey")
        op.drop_column(table, "kb_version_id")
