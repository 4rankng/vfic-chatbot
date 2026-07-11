# ADR-0003: PostgreSQL 16 + pgvector for Relational + Vector Storage

- **Status:** Accepted
- **Date:** 2026-06-26
- **Decider:** Project lead

## Context

The platform needs:
- Relational storage for users, conversations, messages, leads, jobs, knowledge documents, personas, integrations.
- Vector storage for semantic retrieval (RAG): knowledge chunk embeddings (dim 3072) for candidate questions.
- A single database that handles both, running on a 2 vCPU droplet with limited memory.

Options considered: Postgres + pgvector, Postgres + separate vector DB (Qdrant/Milvus), SQLite + vector extension.

## Decision

Use **PostgreSQL 16 + pgvector** as the single database for both relational and vector storage.

Key reasons:
- **Single store.** No operational overhead of running a separate vector DB. One backup, one connection pool, one set of migrations.
- **pgvector HNSW.** Approximate nearest neighbor search with HNSW index for sub-100ms retrieval at the current KB size.
- **Exact re-rank.** After ANN, exact distance computation on top candidates for precision.
- **ACID guarantees.** Knowledge chunk embeddings and their parent documents share transactional integrity.
- **SQL ecosystem.** Alembic migrations, SQLAlchemy ORM, and standard SQL tooling all work natively.

## Consequences

- **Positive:** Simplified ops (one DB to back up, monitor, tune). Transactional consistency between documents and embeddings. No data sync between stores.
- **Negative:** Vector search performance is bounded by Postgres's HNSW implementation — for very large KBs (>1M chunks), a dedicated vector DB may outperform. pgvector adds extension management overhead.
- **Neutral:** Embedding dimension is 3072 (OpenRouter/Gemini) — stored as `vector(3072)` columns. Must ensure HNSW index parameters are tuned for recall vs. speed.

## Related

- ORM models: `backend/app/models/knowledge.py` (`KnowledgeChunk`, `KBVersion`)
- Retrieval: `backend/app/services/retrieval/` (ANN, RRF fusion, reranker)
- Config: `backend/app/core/config.py` (`rag_ann_enabled`, `embedding_dim`)
- Migrations: `backend/alembic/versions/` (pgvector extension setup)
- [docs/system-architecture.md](../system-architecture.md) §10 (RAG retrieval)
- [docs/database.md](../database.md) — DB reference
