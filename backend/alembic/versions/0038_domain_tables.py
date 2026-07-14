"""Domain authority tables: faq_entry + job_* + working_hours.

Tech-Lead Directive §7: authoritative domain tables for FAQ, benefits,
requirements, shifts, locations, working hours. These hold the structured facts
that P1-3's SQL tools will query directly (zero LLM calls for factual lookups).

Bus tables (bus_routes, bus_stops, bus_route_service_days) already exist from
migration 0001 — NOT recreated here. Their ORM models (P1-3) will sit over the
existing schema.

Every time-sensitive table has valid_from / valid_to / status / version (directive §7).
Scope: scope_type ∈ {global, company, location, job_posting, campaign} + scope_id.
Resolution precedence (job > location > company > global) lives in the tool layer.

Reversible via DROP TABLEs in reverse order.
"""

from alembic import op
import sqlalchemy as sa

revision = "0038_domain_tables"
down_revision = "0037_provenance_spine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # faq_entry
    op.create_table(
        "faq_entry",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.String(64), nullable=True),
        sa.Column("canonical_question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="vi"),
        sa.Column("resolution_type", sa.String(16), nullable=False, server_default="static_answer"),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "normalized_question",
            name="uq_faq_entry_scope_normalized_question",
        ),
    )
    op.create_index("ix_faq_entry_scope", "faq_entry", ["scope_type", "scope_id"])
    op.create_index("ix_faq_entry_status", "faq_entry", ["status"])

    # job_requirement
    op.create_table(
        "job_requirement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("min_value", sa.String(64), nullable=True),
        sa.Column("max_value", sa.String(64), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["field_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_requirement_job", "job_requirement", ["job_id"])

    # job_benefit
    op.create_table(
        "job_benefit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="job_posting"),
        sa.Column("scope_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("cadence", sa.String(16), nullable=True),
        sa.Column("eligibility", sa.Text(), nullable=True),
        sa.Column("taxable", sa.Boolean(), nullable=True),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["field_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_benefit_job", "job_benefit", ["job_id"])
    op.create_index("ix_job_benefit_scope", "job_benefit", ["scope_type", "scope_id"])

    # job_shift
    op.create_table(
        "job_shift",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("schedule_type", sa.String(16), nullable=False, server_default="FIXED"),
        sa.Column("days", sa.JSON(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("crosses_midnight", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("breaks", sa.JSON(), nullable=True),
        sa.Column("exceptions", sa.JSON(), nullable=True),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["field_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_shift_job", "job_shift", ["job_id"])

    # job_location
    op.create_table(
        "job_location",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("locality", sa.String(128), nullable=True),
        sa.Column("region", sa.String(128), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["field_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_location_job", "job_location", ["job_id"])

    # working_hours
    op.create_table(
        "working_hours",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.String(64), nullable=True),
        sa.Column("schedule_type", sa.String(16), nullable=False, server_default="FIXED"),
        sa.Column("days", sa.JSON(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("crosses_midnight", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("breaks", sa.JSON(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["evidence_id"], ["field_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_working_hours_scope", "working_hours", ["scope_type", "scope_id"])

    # working_hours_exception
    op.create_table(
        "working_hours_exception",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("working_hours_id", sa.BigInteger(), nullable=False),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["working_hours_id"], ["working_hours.id"], ondelete="CASCADE"),
    )

    # Add section_type to knowledge_chunk (existing table) if not present.
    # The directive requires section_type on projections (P2-7) — add it now
    # so P2-7 doesn't need a separate migration. Idempotent: the column may
    # already exist if a prior deploy added it manually.
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS section_type VARCHAR(32)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS section_type")
    op.drop_index("ix_working_hours_scope", table_name="working_hours")
    op.drop_table("working_hours_exception")
    op.drop_table("working_hours")
    op.drop_index("ix_job_location_job", table_name="job_location")
    op.drop_table("job_location")
    op.drop_index("ix_job_shift_job", table_name="job_shift")
    op.drop_table("job_shift")
    op.drop_index("ix_job_benefit_scope", table_name="job_benefit")
    op.drop_index("ix_job_benefit_job", table_name="job_benefit")
    op.drop_table("job_benefit")
    op.drop_index("ix_job_requirement_job", table_name="job_requirement")
    op.drop_table("job_requirement")
    op.drop_index("ix_faq_entry_status", table_name="faq_entry")
    op.drop_index("ix_faq_entry_scope", table_name="faq_entry")
    op.drop_table("faq_entry")
