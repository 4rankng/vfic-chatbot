"""Cast match_memories to halfvec so the memories HNSW index is usable.

The halfvec(3072) signature and the two ``memories.embedding::halfvec(3072)``
operands below were first edited directly into 0001_baseline.py — a migration
already applied in production, so prod kept the original vector-typed function
and only fresh databases got the halfvec form. The baseline is restored to its
applied (vector) form verbatim and this migration carries the change forward,
so every environment converges on the same definition by running migrations
instead of differing by birth date.

Mirrors migration 0016, which built the memories HNSW index on
``(embedding::halfvec(3072) halfvec_cosine_ops)``: with the original
vector-typed operands the planner cannot use that index for
``memories.embedding <=> query_embedding`` comparisons.

Downgrade restores the original vector-typed function (the verbatim baseline
form) — reversible because CREATE OR REPLACE swaps signatures in place.

Revision ID: 0055_memories_match_halfvec
Revises: 0054_channel_account_projects
Create Date: 2026-09-24
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0055_memories_match_halfvec"
down_revision = "0054_channel_account_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.match_memories(query_embedding halfvec(3072), match_count integer DEFAULT 10, filter jsonb DEFAULT '{}'::jsonb)
        RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision)
        LANGUAGE sql
        STABLE
        SET search_path TO 'public', 'extensions'
        AS $function$
          select
            memories.id,
            memories.content,
            memories.metadata,
            1 - (memories.embedding::halfvec(3072) <=> query_embedding) as similarity
          from public.memories
          where memories.embedding is not null
            and memories.metadata @> filter
          order by memories.embedding::halfvec(3072) <=> query_embedding
          limit match_count;
        $function$;
        """
    )


def downgrade() -> None:
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
