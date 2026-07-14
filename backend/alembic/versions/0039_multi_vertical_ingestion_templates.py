"""Versioned ingestion templates, durable KB runs, and release-scoped facts.

This migration is additive. Existing KB versions remain on the built-in
recruitment compatibility path until a new version is created and pinned to a
published template.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0039_multi_vertical_ingestion_templates"
down_revision = "0038_domain_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE ingestion_template_version_status AS ENUM ('DRAFT', 'PUBLISHED', 'DEPRECATED', 'REVOKED')")
    op.execute("CREATE TYPE kb_ingestion_run_status AS ENUM ('PENDING', 'RUNNING', 'REVIEW_REQUIRED', 'READY', 'FAILED', 'QUARANTINED', 'REJECTED', 'PREVIEW')")
    op.execute("ALTER TYPE kb_version_status ADD VALUE IF NOT EXISTS 'REVIEW_REQUIRED'")

    op.create_table(
        "ingestion_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_key", sa.String(96), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("vertical", sa.String(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("template_key", name="uq_ingestion_template_key"),
    )
    op.create_table(
        "ingestion_template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum(name="ingestion_template_version_status", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("definition", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("compiled_artifact", postgresql.JSONB(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("compiler_version", sa.String(32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["template_id"], ["ingestion_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("template_id", "version_no", name="uq_ingestion_template_version_no"),
    )
    op.add_column("kb_versions", sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("kb_versions", sa.Column("release_manifest_sha256", sa.String(64), nullable=True))
    op.create_foreign_key("fk_kb_versions_template_version", "kb_versions", "ingestion_template_versions", ["template_version_id"], ["id"], ondelete="RESTRICT")
    op.add_column("kb_text_files", sa.Column("source_document_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_kb_text_files_source_document", "kb_text_files", "source_document", ["source_document_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "ingestion_template_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("replaces_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_version_id"], ["ingestion_template_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["replaces_assignment_id"], ["ingestion_template_assignments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "revision", name="uq_ingestion_assignment_revision"),
    )
    op.create_index("ix_ingestion_template_assignment_project", "ingestion_template_assignments", ["project_id", "revision"])

    op.create_table(
        "kb_ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Enum(name="kb_ingestion_run_status", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issues", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["kb_version_id"], ["kb_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_version_id"], ["ingestion_template_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("kb_version_id", "attempt_no", name="uq_kb_ingestion_run_attempt"),
    )
    op.create_index("ix_kb_ingestion_runs_version_status", "kb_ingestion_runs", ["kb_version_id", "status"])
    op.create_table(
        "kb_ingestion_file_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("issues", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["kb_ingestion_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["kb_text_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_document.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", "file_id", name="uq_kb_ingestion_file_run"),
    )
    op.create_table(
        "structured_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kb_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("record_type_key", sa.String(96), nullable=False),
        sa.Column("source_mode", sa.String(24), nullable=False, server_default="sourced_fact"),
        sa.Column("natural_key", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("natural_key_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope_type", sa.String(32), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.String(96), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_version_id"], ["kb_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_version_id"], ["ingestion_template_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["kb_ingestion_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["kb_text_files.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("kb_version_id", "record_type_key", "natural_key_hash", name="uq_structured_fact_release_key"),
    )
    op.create_index("ix_structured_facts_active_lookup", "structured_facts", ["project_id", "kb_version_id", "record_type_key"])
    op.execute("CREATE UNIQUE INDEX uq_active_kb_version_per_project ON kb_versions(project_id) WHERE status = 'ACTIVE'")


def downgrade() -> None:
    op.drop_index("uq_active_kb_version_per_project", table_name="kb_versions")
    op.drop_index("ix_structured_facts_active_lookup", table_name="structured_facts")
    op.drop_table("structured_facts")
    op.drop_table("kb_ingestion_file_runs")
    op.drop_index("ix_kb_ingestion_runs_version_status", table_name="kb_ingestion_runs")
    op.drop_table("kb_ingestion_runs")
    op.drop_index("ix_ingestion_template_assignment_project", table_name="ingestion_template_assignments")
    op.drop_table("ingestion_template_assignments")
    op.drop_constraint("fk_kb_text_files_source_document", "kb_text_files", type_="foreignkey")
    op.drop_column("kb_text_files", "source_document_id")
    op.drop_constraint("fk_kb_versions_template_version", "kb_versions", type_="foreignkey")
    op.drop_column("kb_versions", "release_manifest_sha256")
    op.drop_column("kb_versions", "template_version_id")
    op.drop_table("ingestion_template_versions")
    op.drop_table("ingestion_templates")
    op.execute("DROP TYPE kb_ingestion_run_status")
    op.execute("DROP TYPE ingestion_template_version_status")
