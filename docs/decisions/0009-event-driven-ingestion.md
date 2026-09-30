# ADR-0009: Event-Driven Knowledge Base Ingestion

- **Status:** Accepted
- **Date:** 2026-06-28
- **Decider:** Project lead

## Context

The knowledge base (KB) ingestion pipeline must:
- Accept document uploads (Markdown, DOCX, XLSX, and text files; PDF is not
  supported — there is no extractor).
- Parse, chunk, embed, and store documents for RAG retrieval.
- Support versioned KB releases (KBVersion) with atomic activation.
- Not block the recruiter UI — ingestion can take minutes for large documents.
- Run on a 2 vCPU droplet alongside chat-turn workers.

Options considered: Synchronous ingestion in the API request, async in-process tasks, dedicated RQ queue.

## Decision

Use an **event-driven pipeline** via a dedicated RQ queue (`ingest`), with the following stages:
1. **Upload** — API receives file, creates `KnowledgeDocument` + `KBTextFile` records, enqueues ingest job.
2. **Parse** — Worker extracts text (canonical Markdown parser for `.md`, file extraction for others).
3. **Chunk** — Section-based semantic chunking (per HLD §"Knowledge modeling").
4. **Embed** — Generate embeddings (dim 3072 via Gemini/OpenRouter) for each chunk.
5. **Store** — Insert `KnowledgeChunk` records with vector embeddings into Postgres+pgvector.
6. **Digest** — LLM-generated digest for document-level summarization.
7. **Activate** — KBVersion status transition (draft → active), making chunks available for retrieval.

## Consequences

- **Positive:** Non-blocking — recruiters continue working while ingestion runs in the background. Queue isolation (`ingest` queue) means ingestion never starves chat turns (`webhook_high`). Versioned activation enables atomic KB updates. Failed ingestions are retried by RQ.
- **Negative:** Eventual consistency — newly uploaded documents aren't immediately searchable (must wait for embedding). Recruiters must understand the pipeline status (shown in the KB pipeline timeline UI).
- **Neutral:** The `worker-ingest` container runs separately from `worker-chatbot` — resource isolation. `KBVersion` provides a rollback mechanism (revert to previous active version). Coercion logic (`services/knowledge/coercion.py`) normalizes extracted text before embedding.

## Related

- Ingest worker: `backend/app/workers/ingest_worker.py` (`enqueue_ingest`, `run_ingest_job`, `run_ingest_version_job`)
- Knowledge services: `backend/app/services/knowledge/` (repository, canonical parser, file extraction, coercion, LLM digest)
- Models: `backend/app/models/knowledge.py` (`KnowledgeDocument`, `KnowledgeChunk`, `KBVersion`, `KBTextFile`)
- Pipeline UI: `frontend/src/components/atomic-crm/knowledge/` (pipeline timeline, upload config)
- [docs/system-architecture.md](../architecture/system-architecture.md) — KB pipeline in the data layer
- [docs/HLD.md](../archive/HLD.md) — "Knowledge modeling and storage" section
- [ADR-0003](0003-postgres-pgvector.md) — vector storage
- [ADR-0004](0004-redis-rq-not-celery.md) — queue model
