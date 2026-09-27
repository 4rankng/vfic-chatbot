"""Drop the vector-typed ``match_memories`` overload left behind by 0055.

0055 added ``match_memories(query_embedding halfvec(3072), ...)``, but
``CREATE OR REPLACE`` cannot replace a function whose argument *type* differs —
it only adds an overload. The vector-typed signature from 0001_baseline
therefore survived 0055, and the app kept binding ``CAST(:emb AS vector)``,
which resolved to the exact-compute vector overload. The
``memories_embedding_halfvec_hnsw_idx`` HNSW index from 0016 cannot serve
``memories.embedding <=> <vector>``, so memory recall brute-forced the table on
every ``search_user_memory`` turn.

The app now binds ``CAST(:emb AS halfvec(3072))`` (see
``app/services/retrieval/document_repository.py``). This revision removes the
vector overload so the query cannot resolve back to the exact plan: Postgres
prefers an exact-type match over an implicit cast (``vector -> halfvec`` is
IMPLICIT), so with a single halfvec signature left the call binds to it and its
``embedding::halfvec(3072) <=> <query>`` ORDER BY matches the index expression.

Downgrade restores the vector overload verbatim from 0001_baseline, returning
the database to the pre-0057 two-overload state — 0055's halfvec overload is
left exactly as 0055 leaves it, and a later ``downgrade 0054`` runs 0055's own
downgrade to remove that one.

Revision ID: 0057_drop_match_memories_vector_overload
Revises: 0056_project_external_api
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0057_drop_match_memories_vector_overload"
down_revision = "0056_project_external_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.match_memories(vector, integer, jsonb)")


def downgrade() -> None:
    # 0001_baseline's definition, verbatim — the pre-0055/0057 state.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.match_memories(query_embedding vector, match_count integer DEFAULT 10, filter jsonb DEFAULT '{}'::jsonb)
        RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
        LANGUAGE sql
        STABLE
        SET search_path TO 'public', 'extensions'
        AS $function$
          select
            memories.id,
            memories.content,
            memories.metadata,
            1 - (memories.embedding <=> query_embedding) as similarity
          from public.memories
          where memories.embedding is not null
            and memories.metadata @> filter
          order by memories.embedding <=> query_embedding
          limit match_count;
        $function$;
        """
    )
