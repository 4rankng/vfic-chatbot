"""Retrieval scaling indexes and lexical search text.

Adds:
- ``knowledge_chunks.search_text`` maintained by trigger for indexed lexical fallback.
- halfvec HNSW index for 3072-dim Gemini embeddings, used as ANN candidate generation.
- trigram index for leading-wildcard conversation id search.

Revision ID: 0014_retrieval_scaling_indexes
Revises: 091e7edc9f76
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_retrieval_scaling_indexes"
down_revision = "091e7edc9f76"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("search_text", sa.Text(), nullable=True))
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.knowledge_chunks_set_search_text()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'public', 'extensions'
        AS $$
        BEGIN
          NEW.search_text := public.normalize_search_text(
            COALESCE(NEW.content, '') || ' ' ||
            COALESCE(NEW.source_quote, '') || ' ' ||
            COALESCE(NEW.summary, '')
          );
          RETURN NEW;
        END;
        $$;

        UPDATE public.knowledge_chunks
           SET search_text = public.normalize_search_text(
             COALESCE(content, '') || ' ' ||
             COALESCE(source_quote, '') || ' ' ||
             COALESCE(summary, '')
           )
         WHERE search_text IS NULL;

        DROP TRIGGER IF EXISTS knowledge_chunks_search_text ON public.knowledge_chunks;
        CREATE TRIGGER knowledge_chunks_search_text
          BEFORE INSERT OR UPDATE OF content, source_quote, summary
          ON public.knowledge_chunks
          FOR EACH ROW EXECUTE FUNCTION public.knowledge_chunks_set_search_text();
        """
    )

    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS knowledge_chunks_search_text_trgm_idx
              ON public.knowledge_chunks USING gin (search_text gin_trgm_ops)
              WHERE search_text IS NOT NULL;
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS knowledge_chunks_embedding_halfvec_hnsw_idx
              ON public.knowledge_chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
              WHERE embedding IS NOT NULL;
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS conversations_zalo_chat_id_trgm_idx
              ON public.conversations USING gin (zalo_chat_id gin_trgm_ops);
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.conversations_zalo_chat_id_trgm_idx")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.knowledge_chunks_embedding_halfvec_hnsw_idx")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.knowledge_chunks_search_text_trgm_idx")
    op.execute("DROP TRIGGER IF EXISTS knowledge_chunks_search_text ON public.knowledge_chunks")
    op.execute("DROP FUNCTION IF EXISTS public.knowledge_chunks_set_search_text()")
    op.drop_column("knowledge_chunks", "search_text")
