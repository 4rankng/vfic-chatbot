"""Query-performance indexes (Tier 1 — additive only, zero app change).

Adds ANN and expression indexes that let Postgres use index scans instead of
sequential scans on the hottest query paths:

  C1 — ``memories`` HNSW halfvec index: mirrors the 0014 knowledge_chunks fix.
       The index is built proactively, but the app-side retrieval path
       (``retrieval/repository.py:108-111`` and the ``match_memories`` SQL fn)
       still casts to ``vector``, not ``halfvec``.  pgvector will not use the
       HNSW index until a follow-up adds ``embedding::halfvec(3072) <=> ...``
       to the memories query (mirroring the knowledge_chunks path at
       ``retrieval/repository.py:166``).  This migration is additive and
       harmless — it just means the perf win is deferred to that app change.
  H3 — ``bot_runs`` composite index on ``(outcome, started_at DESC)``: covers
       the dashboard error-count (``outcome='ERROR'``) and the 7-day p95
       latency window (``outcome IN ('SENT','SUPPRESSED') AND started_at > …``).
  H2 — ``messages`` partial index on ``delivery_status`` WHERE ``'FAILED'``:
       the dashboard ``count_failed_sends`` counter currently seq-scans the
       entire append-only messages table.
  H1 — Four expression GIN indexes on ``leads`` for recruiter search:
       ``extensions.unaccent(name/phone/desired_job/zalo_id) ILIKE
       extensions.unaccent('%q%')`` is non-sargable with a leading wildcard and
       no index support.  Expression trigram indexes let the planner match these
       predicates automatically (no app change).  ``zalo_id`` is also wrapped in
       ``unaccent`` in the app query (``lead_service.py:233``), so the index
       expression includes it for planner matching.

Drops three provably-redundant/low-cardinality indexes (A1-A3):
  - ``knowledge_chunks_doc_idx`` — fully covered by the UNIQUE constraint on
    ``(document_id, chunk_index)``.
  - ``job_feature_values_project_idx`` — left-prefix of the UNIQUE
    ``(project_id, feature_id)`` constraint.
  - ``worker_feature_catalog_active_idx`` — boolean column on ~12 rows,
    useless selectivity.

All CREATE/DROP INDEX CONCURRENTLY statements run inside ``autocommit_block()``
(mirrors 0014) because CONCURRENTLY cannot execute inside a transaction.

Revision ID: 0016_query_perf_indexes
Revises: 0015_lead_version_for_oca
Create Date: 2026-06-30
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_query_perf_indexes"
down_revision = "0015_lead_version_for_oca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- A1-A3: drop redundant / low-cardinality indexes -----------------------
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.knowledge_chunks_doc_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.job_feature_values_project_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.worker_feature_catalog_active_idx"
        )

    # -- C1: memories HNSW halfvec index (mirror of 0014 knowledge_chunks fix) ---
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_embedding_halfvec_hnsw_idx
              ON public.memories USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
              WHERE embedding IS NOT NULL;
            """
        )

    # -- H3: bot_runs (outcome, started_at DESC) -------------------------------
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS bot_runs_outcome_started_at_idx
              ON public.bot_runs (outcome, started_at DESC);
            """
        )

    # -- H2: messages partial index on delivery_status='FAILED' ----------------
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_delivery_status_failed_idx
              ON public.messages (delivery_status)
              WHERE delivery_status = 'FAILED';
            """
        )

    # -- H1: lead search expression trigram indexes ----------------------------
    # The extension is installed in the ``extensions`` schema (0001_baseline),
    # not ``public``.  ``unaccent(text)`` is IMMUTABLE when called single-arg
    # with the default rules file.  The planner matches expression indexes to
    # the existing ``extensions.unaccent(col) ILIKE extensions.unaccent('%q%')``
    # predicates in lead_service.py automatically — no app code change needed.
    # zalo_id is wrapped in unaccent in the app query (lead_service.py:233), so
    # the index expression must also include it for planner matching.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_name_unaccent_trgm_idx
              ON public.leads USING gin (extensions.unaccent(name) gin_trgm_ops);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_phone_unaccent_trgm_idx
              ON public.leads USING gin (extensions.unaccent(phone) gin_trgm_ops);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_desired_job_unaccent_trgm_idx
              ON public.leads USING gin (extensions.unaccent(desired_job) gin_trgm_ops);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_zalo_id_trgm_idx
              ON public.leads USING gin (extensions.unaccent(zalo_id) gin_trgm_ops);
            """
        )


def downgrade() -> None:
    # Drop Tier 1 indexes (reverse of upgrade creates)
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.leads_zalo_id_trgm_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.leads_desired_job_unaccent_trgm_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.leads_phone_unaccent_trgm_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.leads_name_unaccent_trgm_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.messages_delivery_status_failed_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.bot_runs_outcome_started_at_idx"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS public.memories_embedding_halfvec_hnsw_idx"
        )

    # Restore A1-A3 redundant indexes (reverse of upgrade drops)
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS knowledge_chunks_doc_idx
              ON public.knowledge_chunks (document_id, chunk_index);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_feature_values_project_idx
              ON public.job_feature_values (project_id);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS worker_feature_catalog_active_idx
              ON public.worker_feature_catalog (is_active);
            """
        )
