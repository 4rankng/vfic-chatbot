"""Stamp bot work and outbound commands with immutable runtime authority.

Revision ID: 0045_runtime_authority_stamps
Revises: 0044_generic_contact_case_kernel
"""

from alembic import op
import sqlalchemy as sa


revision = "0045_runtime_authority_stamps"
down_revision = "0044_generic_contact_case_kernel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("messages", "bot_runs", "outbound_outbox"):
        op.add_column(table, sa.Column("runtime_revision_id", sa.UUID(), nullable=True))
        op.add_column(table, sa.Column("authority_generation", sa.BigInteger(), nullable=True))
        op.add_column(table, sa.Column("runtime_fingerprint", sa.String(64), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_runtime_revision",
            table,
            "installation_manifest_revisions",
            ["runtime_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            f"ck_{table}_runtime_stamp_complete",
            table,
            "(runtime_revision_id IS NULL AND authority_generation IS NULL AND runtime_fingerprint IS NULL) "
            "OR (runtime_revision_id IS NOT NULL AND authority_generation IS NOT NULL "
            "AND authority_generation >= 0 "
            "AND runtime_fingerprint IS NOT NULL "
            "AND runtime_fingerprint ~ '^[0-9a-f]{64}$')",
        )

    op.add_column(
        "outbound_outbox",
        sa.Column("origin_kind", sa.String(24), nullable=True),
    )
    op.add_column(
        "outbound_outbox",
        sa.Column("fence_scope", sa.String(24), nullable=True),
    )
    op.create_check_constraint(
        "ck_outbound_outbox_origin_kind",
        "outbound_outbox",
        "origin_kind IS NULL OR origin_kind IN ('BOT','PROACTIVE','MANUAL')",
    )
    op.create_check_constraint(
        "ck_outbound_outbox_fence_scope",
        "outbound_outbox",
        "fence_scope IS NULL OR fence_scope IN ('RUNTIME','CHANNEL')",
    )
    op.create_check_constraint(
        "ck_outbound_outbox_authority_origin",
        "outbound_outbox",
        "(origin_kind IS NULL AND fence_scope IS NULL) OR "
        "(origin_kind IS NOT NULL AND fence_scope IS NOT NULL AND "
        "((origin_kind IN ('BOT','PROACTIVE') AND fence_scope = 'RUNTIME') OR "
        "(origin_kind = 'MANUAL' AND fence_scope = 'CHANNEL')))",
    )
    op.create_index(
        "ix_outbound_outbox_pending_runtime_authority",
        "outbound_outbox",
        ["runtime_revision_id", "authority_generation", "created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_outbox_pending_runtime_authority", table_name="outbound_outbox")
    op.drop_constraint("ck_outbound_outbox_authority_origin", "outbound_outbox", type_="check")
    op.drop_constraint("ck_outbound_outbox_fence_scope", "outbound_outbox", type_="check")
    op.drop_constraint("ck_outbound_outbox_origin_kind", "outbound_outbox", type_="check")
    op.drop_column("outbound_outbox", "fence_scope")
    op.drop_column("outbound_outbox", "origin_kind")

    for table in ("outbound_outbox", "bot_runs", "messages"):
        op.drop_constraint(f"ck_{table}_runtime_stamp_complete", table, type_="check")
        op.drop_constraint(f"fk_{table}_runtime_revision", table, type_="foreignkey")
        op.drop_column(table, "runtime_fingerprint")
        op.drop_column(table, "authority_generation")
        op.drop_column(table, "runtime_revision_id")
