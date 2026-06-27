"""Replace knowledge approval statuses with published status.

Revision ID: 0006_publish_knowledge_status
Revises: 0005
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op

revision = "0006_publish_knowledge_status"
down_revision = "0005"
branch_labels = None
depends_on = None


_DOCUMENTS_VIEW_SQL = """
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


_MATCH_DOCUMENTS_SQL = """
DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb, uuid[]);
DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb);

CREATE FUNCTION public.match_documents(
  query_embedding vector,
  match_count     integer DEFAULT 10,
  filter          jsonb   DEFAULT '{}'::jsonb,
  project_ids     uuid[]  DEFAULT NULL
)
RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
LANGUAGE plpgsql
SET search_path TO 'public', 'extensions'
AS $function$
begin
  return query
  select
    documents.id,
    documents.content,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) as similarity
  from public.documents
  where documents.embedding is not null
    and documents.metadata @> filter
    and (project_ids is null or documents.project_id = any(project_ids))
  order by documents.embedding <=> query_embedding
  limit match_count;
end;
$function$;
"""


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb, uuid[])")
    op.execute("DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb)")
    op.execute("DROP VIEW IF EXISTS public.documents")
    op.execute("ALTER TABLE public.knowledge_documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE public.knowledge_status RENAME TO knowledge_status_old")
    op.execute(
        "CREATE TYPE public.knowledge_status AS ENUM "
        "('UPLOADED','PROCESSING','PUBLISHED','ARCHIVED','FAILED')"
    )
    op.execute(
        """
        ALTER TABLE public.knowledge_documents
        ALTER COLUMN status TYPE public.knowledge_status
        USING (
          CASE status::text
            WHEN 'APPROVED' THEN 'PUBLISHED'
            WHEN 'READY_FOR_REVIEW' THEN 'PUBLISHED'
            WHEN 'REJECTED' THEN 'ARCHIVED'
            ELSE status::text
          END
        )::public.knowledge_status
        """
    )
    op.execute("ALTER TABLE public.knowledge_documents ALTER COLUMN status SET DEFAULT 'UPLOADED'")
    op.execute("DROP TYPE public.knowledge_status_old")
    op.execute(_DOCUMENTS_VIEW_SQL)
    op.execute(_MATCH_DOCUMENTS_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb, uuid[])")
    op.execute("DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb)")
    op.execute("DROP VIEW IF EXISTS public.documents")
    op.execute("ALTER TABLE public.knowledge_documents ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE public.knowledge_status RENAME TO knowledge_status_new")
    op.execute(
        "CREATE TYPE public.knowledge_status AS ENUM "
        "('UPLOADED','PROCESSING','READY_FOR_REVIEW','APPROVED','REJECTED','ARCHIVED','FAILED')"
    )
    op.execute(
        """
        ALTER TABLE public.knowledge_documents
        ALTER COLUMN status TYPE public.knowledge_status
        USING (
          CASE status::text
            WHEN 'PUBLISHED' THEN 'APPROVED'
            ELSE status::text
          END
        )::public.knowledge_status
        """
    )
    op.execute("ALTER TABLE public.knowledge_documents ALTER COLUMN status SET DEFAULT 'UPLOADED'")
    op.execute("DROP TYPE public.knowledge_status_new")
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
        WHERE kd.status NOT IN ('ARCHIVED', 'REJECTED', 'FAILED');
        """
    )
    op.execute(_MATCH_DOCUMENTS_SQL)
