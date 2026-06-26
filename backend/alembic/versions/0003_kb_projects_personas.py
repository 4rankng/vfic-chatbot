"""Knowledge base per-project + multi-persona + LLM training-pipeline schema.

Adds:
  * ``personas`` — configurable agent personas (free-form markdown body).
  * ``projects`` gains ``is_active``/``summary``/``index_card``/``default_persona_id``
    so a project acts as a "product" in the agent's master index.
  * ``knowledge_documents`` gains ``project_id`` (scope), ``mime_type``/``storage_path``
    (uploaded original), and pipeline-progress columns ``stage``/``digest_summary``/
    ``digest_meta``/``error``.
  * ``knowledge_chunks`` gains ``project_id`` (denormalised for fast scoped filter) and
    the LLM-digest columns ``source_quote``/``summary``/``questions``/``category``/
    ``entities``/``confidence``.
  * ``documents`` VIEW + ``match_documents(...)`` accept a ``project_ids`` filter so
    retrieval can be scoped to the active product(s) the agent selects.

Backwards compatible: existing rows are backfilled to the seeded ``vfic`` project and
no enum is altered (fine-grained progress lives in the free-text ``stage`` column).
Persona seeding (Default VFIC from ``persona.md``) is performed app-side (idempotent
startup seeder); until then ``resolve_persona`` falls back to ``persona.md``, so the
live bot's behaviour is unchanged.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. personas table (created before projects.default_persona_id FK).
    op.execute(
        """
        CREATE TABLE public.personas (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id  uuid REFERENCES public.projects(id) ON DELETE CASCADE,
          name        text NOT NULL,
          slug        text NOT NULL,
          body_md     text NOT NULL,
          is_active   boolean NOT NULL DEFAULT false,
          notes       text,
          created_by  uuid REFERENCES public.users(id) ON DELETE SET NULL,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX personas_slug_key ON public.personas (slug);
        -- At most one active *global* persona (project_id IS NULL). The constant
        -- expression trick enforces singularity among rows matching the predicate;
        -- the activate endpoint also deactivates siblings transactionally.
        CREATE UNIQUE INDEX personas_one_active_global
          ON public.personas ((1)) WHERE is_active AND project_id IS NULL;
        CREATE TRIGGER personas_touch
          BEFORE UPDATE ON public.personas
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )

    # 2. projects gains product-catalog + persona columns.
    op.execute(
        """
        ALTER TABLE public.projects
          ADD COLUMN is_active          boolean NOT NULL DEFAULT true,
          ADD COLUMN summary            text,
          ADD COLUMN index_card         jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN default_persona_id uuid REFERENCES public.personas(id) ON DELETE SET NULL,
          ADD COLUMN updated_at         timestamptz NOT NULL DEFAULT now();
        CREATE TRIGGER projects_touch
          BEFORE UPDATE ON public.projects
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )

    # 3. NOTE: the canonical 'vfic' project is NOT seeded here. Seeding a row with a
    #    random uuid would collide with test code (and future app inserts) that rely
    #    on inserting their own 'vfic' row by slug into an empty table. The 'vfic'
    #    project + the Default persona are ensured idempotently at app startup
    #    (Phase 3). The project_id backfill below is a safe no-op until that row
    #    exists (the column is nullable).

    # 4. knowledge_documents gains project scope + upload/pipeline columns.
    op.execute(
        """
        ALTER TABLE public.knowledge_documents
          ADD COLUMN project_id      uuid REFERENCES public.projects(id) ON DELETE SET NULL,
          ADD COLUMN mime_type       text,
          ADD COLUMN storage_path    text,
          ADD COLUMN stage           text NOT NULL DEFAULT 'UPLOADED',
          ADD COLUMN digest_summary  text,
          ADD COLUMN digest_meta     jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN error           text;
        UPDATE public.knowledge_documents
           SET project_id = (SELECT id FROM public.projects WHERE slug = 'vfic')
         WHERE project_id IS NULL;
        CREATE INDEX knowledge_documents_project_idx ON public.knowledge_documents (project_id);
        """
    )

    # 5. knowledge_chunks gains project scope (denormalised) + LLM-digest columns.
    op.execute(
        """
        ALTER TABLE public.knowledge_chunks
          ADD COLUMN project_id   uuid,
          ADD COLUMN source_quote text,
          ADD COLUMN summary      text,
          ADD COLUMN questions    text[] NOT NULL DEFAULT '{}'::text[],
          ADD COLUMN category     text,
          ADD COLUMN entities     jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN confidence   text;
        UPDATE public.knowledge_chunks kc
           SET project_id = kd.project_id
          FROM public.knowledge_documents kd
         WHERE kd.id = kc.document_id;
        CREATE INDEX knowledge_chunks_project_idx ON public.knowledge_chunks (project_id);
        """
    )

    # 6. documents VIEW + match_documents RPC accept project scoping. The VIEW gains
    #    project_id (appended last so existing column order/selects are unaffected).
    #    NB: CREATE OR REPLACE FUNCTION cannot change a function's argument signature,
    #    so we DROP the old (vector,int,jsonb) overload first; existing 3-arg callers
    #    still resolve to the new function via the project_ids DEFAULT (== no filter).
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
        WHERE kd.status = 'APPROVED';

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
    )


def downgrade() -> None:
    # Restore the original 3-arg match_documents + project-less view. Drop the 4-arg
    # overload first so we don't leave both signatures in place.
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.match_documents(vector, integer, jsonb, uuid[]);

        CREATE FUNCTION public.match_documents(query_embedding vector, match_count integer DEFAULT 10, filter jsonb DEFAULT '{}'::jsonb)
        RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
        LANGUAGE plpgsql
        SET search_path TO 'public', 'extensions'
        AS $function$
        begin
          return query
          select documents.id, documents.content, documents.metadata,
                 1 - (documents.embedding <=> query_embedding) as similarity
          from public.documents
          where documents.embedding is not null
            and documents.metadata @> filter
          order by documents.embedding <=> query_embedding
          limit match_count;
        end;
        $function$;

        CREATE OR REPLACE VIEW public.documents AS
        SELECT
          kd.id            AS id,
          kc.content       AS content,
          kd.metadata      AS metadata,
          kc.embedding     AS embedding,
          kd.drive_file_id AS drive_file_id,
          kd.source        AS source
        FROM public.knowledge_documents kd
        JOIN public.knowledge_chunks kc ON kc.document_id = kd.id
        WHERE kd.status = 'APPROVED';
        """
    )
    op.execute("DROP INDEX IF EXISTS public.knowledge_chunks_project_idx")
    op.execute(
        "ALTER TABLE public.knowledge_chunks "
        "DROP COLUMN IF EXISTS confidence, DROP COLUMN IF EXISTS entities, "
        "DROP COLUMN IF EXISTS category, DROP COLUMN IF EXISTS questions, "
        "DROP COLUMN IF EXISTS summary, DROP COLUMN IF EXISTS source_quote, "
        "DROP COLUMN IF EXISTS project_id"
    )
    op.execute("DROP INDEX IF EXISTS public.knowledge_documents_project_idx")
    op.execute(
        "ALTER TABLE public.knowledge_documents "
        "DROP COLUMN IF EXISTS error, DROP COLUMN IF EXISTS digest_meta, "
        "DROP COLUMN IF EXISTS digest_summary, DROP COLUMN IF EXISTS stage, "
        "DROP COLUMN IF EXISTS storage_path, DROP COLUMN IF EXISTS mime_type, "
        "DROP COLUMN IF EXISTS project_id"
    )
    op.execute("DROP TRIGGER IF EXISTS projects_touch ON public.projects")
    op.execute(
        "ALTER TABLE public.projects "
        "DROP COLUMN IF EXISTS updated_at, DROP COLUMN IF EXISTS default_persona_id, "
        "DROP COLUMN IF EXISTS index_card, DROP COLUMN IF EXISTS summary, "
        "DROP COLUMN IF EXISTS is_active"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS personas_touch ON public.personas; "
        "DROP TABLE IF EXISTS public.personas CASCADE;"
    )
