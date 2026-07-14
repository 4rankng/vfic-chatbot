"""Provenance spine: source_document, source_fragment, extraction_run, field_evidence.

Tech-Lead Directive §7 + §11: "The database must distinguish between authoritative
domain data, search documents derived from that data, and raw source evidence.
Do not use embeddings as the source of truth."

This migration creates the four-table provenance spine that ALL extracted
authoritative data references back to. Every material field published to a
domain table (job_benefit, working_hours, etc. — later migrations) carries a
``field_evidence`` row linking it to the exact source fragment + extraction method.

Tables:
- source_document: immutable original upload (sha256, mime, storage_uri)
- source_fragment: structure-aware chunks (section_path, block_type, table_json)
- extraction_run: one pass of extraction over a document (status, schema_version)
- field_evidence: per-field provenance (field_path → source_fragment + method + confidence)

Reversible via 4 DROP TABLEs in reverse dependency order.
"""

from alembic import op
import sqlalchemy as sa

revision = "0037_provenance_spine"
down_revision = "0036_outbound_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. source_document — the immutable original.
    op.create_table(
        "source_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True, comment="Owning project (NULL = cross-project)"),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("storage_uri", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="RECEIVED"),
        sa.Column("parser_version", sa.String(32), nullable=True),
        sa.Column("extractor_version", sa.String(32), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True, comment="User who uploaded"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("sha256", "project_id", name="uq_source_document_sha256_project"),
        sa.CheckConstraint(
            "status IN ('RECEIVED','STORED','PARSED','NORMALIZED','CLASSIFIED',"
            "'EXTRACTED','VALIDATED','REVIEW_REQUIRED','APPROVED','PUBLISHED',"
            "'INDEXED','FAILED_TRANSIENT','FAILED_PERMANENT','QUARANTINED','SUPERSEDED')",
            name="ck_source_document_status",
        ),
    )
    op.create_index("ix_source_document_status", "source_document", ["status"])
    op.create_index("ix_source_document_project", "source_document", ["project_id"])

    # 2. source_fragment — structure-aware chunks of a document.
    op.create_table(
        "source_fragment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.String(512), nullable=True, comment="Heading hierarchy e.g. 'Phúc lợi > Chuyên cần'"),
        sa.Column("block_type", sa.String(32), nullable=False, comment="title|section|paragraph|list|table|table_row|table_cell"),
        sa.Column("block_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("section_type", sa.String(32), nullable=True, comment="faq|bus_timetable|benefit|working_hours|job_requirements|salary|location|application_process|general_policy|unknown"),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("table_json", sa.JSON(), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("fragment_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["source_document.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_source_fragment_document", "source_fragment", ["document_id"])
    op.create_index("ix_source_fragment_section_type", "source_fragment", ["section_type"])

    # 3. extraction_run — one pass of extraction over a document.
    op.create_table(
        "extraction_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_version", sa.String(32), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True, comment="Counts per entity_type + warnings"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_document.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','REVIEW_REQUIRED')",
            name="ck_extraction_run_status",
        ),
    )
    op.create_index("ix_extraction_run_document", "extraction_run", ["source_document_id"])

    # 4. field_evidence — per-field provenance (the directive's §11 core).
    op.create_table(
        "field_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("extraction_run_id", sa.BigInteger(), nullable=False),
        sa.Column("source_fragment_id", sa.BigInteger(), nullable=True),
        sa.Column("field_path", sa.String(256), nullable=False, comment="e.g. data.trips[0].stops[0].departure_time"),
        sa.Column("value", sa.Text(), nullable=True, comment="The extracted value (text form for any type)"),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("table_row", sa.Integer(), nullable=True),
        sa.Column("table_column", sa.Integer(), nullable=True),
        sa.Column("char_range", sa.String(32), nullable=True, comment="start:end"),
        sa.Column("extraction_method", sa.String(32), nullable=False, comment="table_parser|regex|llm_extractor|deterministic"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_fragment_id"], ["source_fragment.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_field_evidence_run", "field_evidence", ["extraction_run_id"])
    op.create_index("ix_field_evidence_fragment", "field_evidence", ["source_fragment_id"])


def downgrade() -> None:
    op.drop_index("ix_field_evidence_fragment", table_name="field_evidence")
    op.drop_index("ix_field_evidence_run", table_name="field_evidence")
    op.drop_table("field_evidence")
    op.drop_index("ix_extraction_run_document", table_name="extraction_run")
    op.drop_table("extraction_run")
    op.drop_index("ix_source_fragment_section_type", table_name="source_fragment")
    op.drop_index("ix_source_fragment_document", table_name="source_fragment")
    op.drop_table("source_fragment")
    op.drop_index("ix_source_document_project", table_name="source_document")
    op.drop_index("ix_source_document_status", table_name="source_document")
    op.drop_table("source_document")
