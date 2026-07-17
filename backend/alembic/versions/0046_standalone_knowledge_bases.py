"""Add standalone, shareable Agent knowledge bases.

Revision ID: 0046_standalone_knowledge_bases
Revises: 0045_runtime_authority_stamps

The schema is intentionally tenant-neutral.  It creates no named KB, Persona,
or Project: deployment-specific legacy assignments are performed through the
audited bootstrap operation after this additive migration succeeds.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0046_standalone_knowledge_bases"
down_revision = "0045_runtime_authority_stamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE knowledge_base_mode AS ENUM ('RAG', 'DIRECT_CONTEXT')")
    op.create_table(
        "knowledge_bases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(96), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(name="knowledge_base_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9._-]*$'", name="knowledge_bases_slug_canonical"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("slug", name="uq_knowledge_bases_slug"),
    )
    op.create_table(
        "knowledge_base_direct_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("char_count > 0", name="knowledge_base_direct_files_nonempty"),
        sa.CheckConstraint("line_count > 0", name="knowledge_base_direct_files_lines_positive"),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="knowledge_base_direct_files_checksum"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("knowledge_base_id", name="uq_knowledge_base_direct_file"),
    )
    op.add_column("personas", sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_personas_knowledge_base",
        "personas",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_personas_knowledge_base", "personas", ["knowledge_base_id"])
    op.add_column("projects", sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_projects_knowledge_base",
        "projects",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_knowledge_base", "projects", ["knowledge_base_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_knowledge_base", table_name="projects")
    op.drop_constraint("fk_projects_knowledge_base", "projects", type_="foreignkey")
    op.drop_column("projects", "knowledge_base_id")
    op.drop_index("ix_personas_knowledge_base", table_name="personas")
    op.drop_constraint("fk_personas_knowledge_base", "personas", type_="foreignkey")
    op.drop_column("personas", "knowledge_base_id")
    op.drop_table("knowledge_base_direct_files")
    op.drop_table("knowledge_bases")
    op.execute("DROP TYPE knowledge_base_mode")
