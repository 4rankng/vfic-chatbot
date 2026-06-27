"""Remove manual approval gate from knowledge retrieval.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW public.documents AS
        SELECT
          kd.id            AS id,
          kc.content       AS content,
          kd.metadata      AS metadata,
          kc.embedding     AS embedding,
          kd.drive_file_id AS drive_file_id,
          kd.source        AS source,
          kd.project_id    AS project_id
        FROM public.knowledge_documents kd
        JOIN public.knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status NOT IN ('ARCHIVED', 'FAILED');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW public.documents AS
        SELECT
          kd.id            AS id,
          kc.content       AS content,
          kd.metadata      AS metadata,
          kc.embedding     AS embedding,
          kd.drive_file_id AS drive_file_id,
          kd.source        AS source,
          kd.project_id    AS project_id
        FROM public.knowledge_documents kd
        JOIN public.knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status = 'PUBLISHED';
        """
    )
