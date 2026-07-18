"""Add Project-owned knowledge modes and independent RAG category revisions.

Revision ID: 0048_project_owned_knowledge_modes
Revises: 0047_canonical_channel_identity

The migration is additive. Existing shared/global knowledge bases stay
unassigned because their Project ownership cannot be inferred safely.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0048_project_owned_knowledge_modes"
down_revision = "0047_canonical_channel_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE knowledge_category_revision_status AS ENUM "
        "('STAGED', 'PROCESSING', 'ACTIVE', 'ARCHIVED', 'FAILED', 'CLEARED')"
    )

    op.add_column("knowledge_bases", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_bases_project",
        "knowledge_bases",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_knowledge_bases_project",
        "knowledge_bases",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )

    op.add_column(
        "projects",
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.execute(
        """
        UPDATE projects AS p
        SET aliases = source.aliases
        FROM (
            SELECT project_id, array_agg(DISTINCT alias) AS aliases
            FROM (
                SELECT project_id, name AS alias FROM companies
                UNION ALL
                SELECT project_id, unnest(aliases) AS alias FROM companies
            ) AS values_by_project
            WHERE alias IS NOT NULL AND btrim(alias) <> ''
            GROUP BY project_id
        ) AS source
        WHERE p.id = source.project_id
        """
    )
    op.add_column(
        "projects",
        sa.Column("discovery_revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "category_authority_started",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "conversations",
        sa.Column("project_context_state", sa.String(16), nullable=False, server_default="EXPLORE"),
    )
    op.add_column(
        "conversations",
        sa.Column("focused_project_id", sa.UUID(), nullable=True),
    )
    op.create_check_constraint(
        "conversation_project_context_values",
        "conversations",
        "project_context_state IN ('EXPLORE', 'FOCUSED')",
    )
    op.create_foreign_key(
        "fk_conversations_focused_project",
        "conversations",
        "projects",
        ["focused_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversations_focused_project",
        "conversations",
        ["focused_project_id"],
        postgresql_where=sa.text("focused_project_id IS NOT NULL"),
    )

    op.create_table(
        "knowledge_categories",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category_key", sa.String(32), nullable=False),
        sa.Column("active_revision_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "category_key", name="uq_knowledge_categories_project_key"),
        sa.CheckConstraint(
            "category_key IN ('jobs', 'compensation', 'requirements', 'work_schedules', "
            "'benefits', 'accommodation', 'meals', 'transportation', 'insurance', "
            "'application', 'contacts', 'faq')",
            name="knowledge_category_key_values",
        ),
    )
    op.create_index("ix_knowledge_categories_project", "knowledge_categories", ["project_id"])

    # Migrate legacy RAG ownership only when the existing relationship is
    # unambiguous: exactly one Project already points at that KB. Production's
    # existing LG Display KB satisfies this guard. Shared/global KBs remain
    # unresolved and untouched.
    op.execute(
        """
        UPDATE knowledge_bases AS kb
        SET project_id = candidate.project_id
        FROM (
            SELECT knowledge_base_id, (array_agg(id ORDER BY id))[1] AS project_id
            FROM projects
            WHERE knowledge_base_id IS NOT NULL
            GROUP BY knowledge_base_id
            HAVING count(*) = 1
        ) AS candidate
        WHERE kb.id = candidate.knowledge_base_id
          AND kb.mode = 'RAG'
          AND kb.project_id IS NULL
        """
    )
    # Production fallback: the deployment currently has one legacy RAG KB and
    # one unambiguous LG Display Project. Link them even if the earlier
    # standalone-KB bootstrap did not populate projects.knowledge_base_id.
    op.execute(
        """
        WITH sole_rag AS (
            SELECT (array_agg(id ORDER BY id))[1] AS knowledge_base_id
            FROM knowledge_bases
            WHERE mode = 'RAG'
            HAVING count(*) = 1
        ),
        lg_candidates AS (
            SELECT DISTINCT p.id AS project_id
            FROM projects AS p
            LEFT JOIN companies AS c ON c.project_id = p.id
            WHERE lower(p.name) LIKE '%lg%display%'
               OR lower(p.slug) LIKE '%lg%display%'
               OR lower(coalesce(c.name, '')) LIKE '%lg%display%'
        ),
        sole_lg AS (
            SELECT (array_agg(project_id ORDER BY project_id))[1] AS project_id
            FROM lg_candidates
            HAVING count(*) = 1
        )
        UPDATE knowledge_bases AS kb
        SET project_id = sole_lg.project_id
        FROM sole_rag, sole_lg
        WHERE kb.id = sole_rag.knowledge_base_id
          AND kb.project_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM knowledge_bases AS owned
              WHERE owned.project_id = sole_lg.project_id
          )
        """
    )
    op.create_index(
        "uq_projects_knowledge_base_owned",
        "projects",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("knowledge_base_id IS NOT NULL"),
    )
    op.execute(
        """
        UPDATE projects AS p
        SET knowledge_base_id = kb.id
        FROM knowledge_bases AS kb
        WHERE kb.project_id = p.id
          AND kb.mode = 'RAG'
          AND p.knowledge_base_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO knowledge_categories (project_id, category_key)
        SELECT kb.project_id, category_key
        FROM knowledge_bases AS kb
        CROSS JOIN unnest(ARRAY[
            'jobs', 'compensation', 'requirements', 'work_schedules',
            'benefits', 'accommodation', 'meals', 'transportation',
            'insurance', 'application', 'contacts', 'faq'
        ]) AS category_key
        WHERE kb.mode = 'RAG' AND kb.project_id IS NOT NULL
        ON CONFLICT (project_id, category_key) DO NOTHING
        """
    )

    op.create_table(
        "knowledge_category_revisions",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="knowledge_category_revision_status", create_type=False),
            nullable=False,
            server_default="STAGED",
        ),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_yaml", sa.Text(), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["knowledge_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("category_id", "revision_no", name="uq_category_revisions_number"),
        sa.CheckConstraint("revision_no > 0", name="category_revision_number_positive"),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="category_revision_checksum",
        ),
    )
    op.create_index(
        "ix_category_revisions_category_status",
        "knowledge_category_revisions",
        ["category_id", "status"],
    )
    op.create_foreign_key(
        "fk_knowledge_categories_active_revision",
        "knowledge_categories",
        "knowledge_category_revisions",
        ["active_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "knowledge_documents",
        sa.Column("category_revision_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_documents_category_revision",
        "knowledge_documents",
        "knowledge_category_revisions",
        ["category_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_knowledge_documents_category_revision",
        "knowledge_documents",
        ["category_revision_id"],
        unique=True,
        postgresql_where=sa.text("category_revision_id IS NOT NULL"),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("category_revision_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_chunks_category_revision",
        "knowledge_chunks",
        "knowledge_category_revisions",
        ["category_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_knowledge_chunks_category_revision",
        "knowledge_chunks",
        ["category_revision_id"],
    )

    op.add_column("jobs", sa.Column("stable_key", sa.String(64), nullable=True))
    op.add_column("jobs", sa.Column("source_category_revision_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_source_category_revision",
        "jobs",
        "knowledge_category_revisions",
        ["source_category_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_jobs_source_category_revision",
        "jobs",
        ["source_category_revision_id"],
        postgresql_where=sa.text("source_category_revision_id IS NOT NULL"),
    )
    op.add_column(
        "bus_routes",
        sa.Column("source_category_revision_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bus_routes_source_category_revision",
        "bus_routes",
        "knowledge_category_revisions",
        ["source_category_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_bus_routes_source_category_revision",
        "bus_routes",
        ["source_category_revision_id"],
        postgresql_where=sa.text("source_category_revision_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_bus_routes_source_category_revision", table_name="bus_routes")
    op.drop_constraint(
        "fk_bus_routes_source_category_revision",
        "bus_routes",
        type_="foreignkey",
    )
    op.drop_column("bus_routes", "source_category_revision_id")
    op.drop_index("ix_jobs_source_category_revision", table_name="jobs")
    op.drop_constraint("fk_jobs_source_category_revision", "jobs", type_="foreignkey")
    op.drop_column("jobs", "source_category_revision_id")
    op.drop_column("jobs", "stable_key")

    op.drop_index("ix_knowledge_chunks_category_revision", table_name="knowledge_chunks")
    op.drop_constraint(
        "fk_knowledge_chunks_category_revision", "knowledge_chunks", type_="foreignkey"
    )
    op.drop_column("knowledge_chunks", "category_revision_id")
    op.drop_index("uq_knowledge_documents_category_revision", table_name="knowledge_documents")
    op.drop_constraint(
        "fk_knowledge_documents_category_revision", "knowledge_documents", type_="foreignkey"
    )
    op.drop_column("knowledge_documents", "category_revision_id")

    op.drop_constraint(
        "fk_knowledge_categories_active_revision", "knowledge_categories", type_="foreignkey"
    )
    op.drop_index("ix_category_revisions_category_status", table_name="knowledge_category_revisions")
    op.drop_table("knowledge_category_revisions")
    op.drop_index("ix_knowledge_categories_project", table_name="knowledge_categories")
    op.drop_table("knowledge_categories")

    op.drop_index("ix_conversations_focused_project", table_name="conversations")
    op.drop_constraint("fk_conversations_focused_project", "conversations", type_="foreignkey")
    op.drop_constraint("conversation_project_context_values", "conversations", type_="check")
    op.drop_column("conversations", "focused_project_id")
    op.drop_column("conversations", "project_context_state")

    op.drop_column("projects", "category_authority_started")
    op.drop_column("projects", "discovery_revision")
    op.drop_column("projects", "aliases")
    op.drop_index("uq_projects_knowledge_base_owned", table_name="projects")
    op.drop_index("uq_knowledge_bases_project", table_name="knowledge_bases")
    op.drop_constraint("fk_knowledge_bases_project", "knowledge_bases", type_="foreignkey")
    op.drop_column("knowledge_bases", "project_id")
    op.execute("DROP TYPE knowledge_category_revision_status")
