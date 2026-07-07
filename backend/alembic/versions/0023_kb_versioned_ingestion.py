"""Add project-scoped KB versions and text-file ingestion.

Revision ID: 0023_kb_versioned_ingestion
Revises: 0022_lead_chatops_tags
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_kb_versioned_ingestion"
down_revision = "0022_lead_chatops_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'kb_version_status') THEN
            CREATE TYPE public.kb_version_status AS ENUM
              ('DRAFT','INDEXING','READY','ACTIVE','ARCHIVED','FAILED');
          END IF;
        END
        $$;
        """
    )

    op.create_table(
        "kb_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "DRAFT",
                "INDEXING",
                "READY",
                "ACTIVE",
                "ARCHIVED",
                "FAILED",
                name="kb_version_status",
                create_type=False,
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version_no", name="uq_kb_versions_project_version"),
        schema="public",
    )
    op.create_index("ix_kb_versions_project_status", "kb_versions", ["project_id", "status"], schema="public")

    op.add_column("projects", sa.Column("active_kb_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_projects_active_kb_version_id",
        "projects",
        "kb_versions",
        ["active_kb_version_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )

    op.create_table(
        "kb_text_files",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kb_version_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), server_default="text/plain", nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["kb_version_id"], ["kb_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kb_version_id", "content_sha256", name="uq_kb_text_files_version_sha"),
        schema="public",
    )
    op.create_index("ix_kb_text_files_version", "kb_text_files", ["kb_version_id"], schema="public")

    op.add_column("knowledge_chunks", sa.Column("kb_version_id", sa.UUID(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("file_id", sa.UUID(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("chunk_type", sa.Text(), server_default="text", nullable=False))
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "section_path",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )
    op.add_column("knowledge_chunks", sa.Column("line_start", sa.Integer(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("line_end", sa.Integer(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("content_plain", sa.Text(), nullable=True))
    op.add_column("knowledge_chunks", sa.Column("token_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("knowledge_chunks", sa.Column("chunk_sha256", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_chunks_kb_version_id",
        "knowledge_chunks",
        "kb_versions",
        ["kb_version_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_chunks_file_id",
        "knowledge_chunks",
        "kb_text_files",
        ["file_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
    )

    # Best-effort bridge for existing rows: one active version per project and one
    # text file per existing knowledge document. New code reads only active-version
    # chunks, so this preserves current production knowledge after migration.
    op.execute(
        """
        INSERT INTO public.kb_versions (project_id, version_no, status, created_at, published_at)
        SELECT p.id, 1, 'ACTIVE'::public.kb_version_status, now(), now()
        FROM public.projects p
        WHERE EXISTS (
          SELECT 1 FROM public.knowledge_documents kd
          WHERE kd.project_id = p.id AND kd.status NOT IN ('ARCHIVED','FAILED')
        )
        ON CONFLICT (project_id, version_no) DO NOTHING;

        UPDATE public.projects p
           SET active_kb_version_id = kv.id
          FROM public.kb_versions kv
         WHERE kv.project_id = p.id
           AND kv.version_no = 1
           AND p.active_kb_version_id IS NULL;

        INSERT INTO public.kb_text_files (
          project_id, kb_version_id, document_id, filename, mime_type, raw_text,
          normalized_text, content_sha256, char_count, line_count, created_at
        )
        SELECT
          kd.project_id,
          kv.id,
          kd.id,
          kd.file_name,
          COALESCE(kd.mime_type, 'text/plain'),
          COALESCE(kd.raw_text, ''),
          COALESCE(kd.raw_text, ''),
          encode(digest(COALESCE(kd.raw_text, ''), 'sha256'), 'hex'),
          length(COALESCE(kd.raw_text, '')),
          CASE
            WHEN COALESCE(kd.raw_text, '') = '' THEN 0
            ELSE array_length(regexp_split_to_array(COALESCE(kd.raw_text, ''), E'\\n'), 1)
          END,
          kd.created_at
        FROM public.knowledge_documents kd
        JOIN public.kb_versions kv ON kv.project_id = kd.project_id AND kv.version_no = 1
        WHERE kd.project_id IS NOT NULL
        ON CONFLICT (kb_version_id, content_sha256) DO NOTHING;

        UPDATE public.knowledge_chunks kc
           SET kb_version_id = ktf.kb_version_id,
               file_id = ktf.id,
               project_id = kd.project_id,
               content_plain = public.normalize_search_text(
                 COALESCE(kc.content, '') || ' ' ||
                 COALESCE(kc.source_quote, '') || ' ' ||
                 COALESCE(kc.summary, '')
               ),
               token_count = GREATEST(
                 cardinality(regexp_split_to_array(btrim(COALESCE(kc.content, '')), E'\\s+')),
                 0
               ),
               chunk_sha256 = encode(digest(COALESCE(kc.content, ''), 'sha256'), 'hex'),
               chunk_type = COALESCE(kc.category, 'text')
        FROM public.knowledge_documents kd
        JOIN public.kb_text_files ktf ON ktf.document_id = kd.id
        WHERE kc.document_id = kd.id;
        """
    )

    op.create_index(
        "ix_knowledge_chunks_version_file",
        "knowledge_chunks",
        ["kb_version_id", "file_id", "chunk_index"],
        schema="public",
    )
    op.create_index(
        "ix_knowledge_chunks_scope_version",
        "knowledge_chunks",
        ["project_id", "kb_version_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_scope_version", table_name="knowledge_chunks", schema="public")
    op.drop_index("ix_knowledge_chunks_version_file", table_name="knowledge_chunks", schema="public")
    op.drop_constraint("fk_knowledge_chunks_file_id", "knowledge_chunks", schema="public", type_="foreignkey")
    op.drop_constraint(
        "fk_knowledge_chunks_kb_version_id",
        "knowledge_chunks",
        schema="public",
        type_="foreignkey",
    )
    for column in (
        "chunk_sha256",
        "token_count",
        "content_plain",
        "line_end",
        "line_start",
        "section_path",
        "chunk_type",
        "file_id",
        "kb_version_id",
    ):
        op.drop_column("knowledge_chunks", column)
    op.drop_index("ix_kb_text_files_version", table_name="kb_text_files", schema="public")
    op.drop_table("kb_text_files", schema="public")
    op.drop_constraint(
        "fk_projects_active_kb_version_id",
        "projects",
        schema="public",
        type_="foreignkey",
    )
    op.drop_column("projects", "active_kb_version_id")
    op.drop_index("ix_kb_versions_project_status", table_name="kb_versions", schema="public")
    op.drop_table("kb_versions", schema="public")
    op.execute("DROP TYPE IF EXISTS public.kb_version_status")
