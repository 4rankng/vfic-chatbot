---
type: system
title: Knowledge ingestion pipeline and category worker
description: From upload to pgvector — parse → canonicalize → digest (LLM) → embed → write — plus the version-ingest path, the category worker that reconciles project taxonomy, and the recovery semantics introduced by migration 0050.
tags: [ingestion, embedding, pgvector, digest, category-worker, recovery, kb-versions]
sources:
  - id: openwiki-source-8de84e18d91ee444093db299
    resource: repo://backend/alembic/versions/0050_data_ingestion_recovery.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-5574cf20a4a54da71db2064d
    resource: repo://backend/app/project_knowledge/application/ingestion.py
  - id: openwiki-source-8b3f344ba618d78945c34953
    resource: repo://backend/app/project_knowledge/domain/ingestion.py
  - id: openwiki-source-1b434f0e5428d339d9c27769
    resource: repo://backend/app/workers/category_worker.py
  - id: openwiki-source-fb4738e80917294d18cfb99e
    resource: repo://backend/app/workers/ingest_worker.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

The ingestion pipeline runs on the `ingest` RQ queue (`worker-ingest`,
single replica). It owns the path that turns an uploaded file into
indexable pgvector rows, and the path that promotes a KB version to
"live" once it's safe to serve. Two worker entry points exist so the
doc-level and version-level paths share the same composition root but
fail independently.

## Constants and the timeout envelope

The pipeline's tunables live in `backend/app/core/config.py`:

| Constant | Default | Role |
|---|---|---|
| `DIGEST_SECTION_CHARS` | 6000 | Window size for digest chunking |
| `DIGEST_SECTION_OVERLAP` | 400 | Overlap between consecutive sections |
| `DIGEST_MAX_SECTIONS` | 20 | Hard cap on sections per document |
| `INGEST_JOB_TIMEOUT_SECONDS` | 3600 | RQ `job_timeout` for every `ingest` job (document ingest, version ingest, category revision) |

`INGEST_JOB_TIMEOUT_SECONDS` is a code constant — a deployment knob here
would change the worst-case cost of a malicious or runaway doc and is
deliberately not env-tunable.

## Pipeline topology

The shared composition root is
`app/composition/project_knowledge.build_knowledge_ingestion_use_cases(db)`.
It returns a `KnowledgeIngestionUseCases` whose
`ingest_document(document_id, embedder=None, json_extractor=None)` and
`ingest_version(version_id, embedder=None, json_extractor=None)` are the
two entry points. `embedder` and `json_extractor` are injectable for
tests; production callers pass `None` and the use cases resolve them
from the cached LLM clients (`graph.factories._build_cached_clients`).

### Document ingest

```text
enqueue_ingest(doc_id)                       # workers/ingest_worker.py
  → enqueue_job("ingest", run_ingest_job, str(doc_id), job_timeout=INGEST_JOB_TIMEOUT_SECONDS)
RQ worker dequeue
  → run_async(_run_job_async(doc_id))
        → worker_session() opens a fresh DB session
        → build_knowledge_ingestion_use_cases(db).ingest_document(...)
              parse → canonicalize → digest (LLM) → embed → write to pgvector
        → repository writes the indexed document status
```

The canonical Markdown path uses a deterministic `parse → embed → index`
flow. Legacy / freeform jobs use the full `digest (MiniMax / OpenRouter)
→ embed (configured provider) → index` path. The worker module's
docstring is explicit about both paths.

### Version ingest

```text
enqueue_ingest_version(version_id) → enqueue_job("ingest", run_ingest_version_job,
                                                 job_id=f"knowledge-version-{version_id}")
  → run_ingest_version_job(version_id)
        → run_async(_run_version_job_async(version_id))
              → worker_session() opens a fresh DB session
              → build_knowledge_ingestion_use_cases(db).ingest_version(...)
```

The deterministic `job_id=f"knowledge-version-{version_id}"` is a receipt
id so re-enqueue is a no-op and an existing in-flight version can be
introspected. `enqueue_ingest_version` raises `RuntimeError("knowledge
version enqueue failed")` when the enqueue returns `None` so the
admin UI surfaces a failure rather than silently dropping the version.

### Category revision worker

`backend/app/workers/category_worker.py` runs deterministic Project
RAG-category activations on the same `ingest` queue.

```text
enqueue_category_revision(revision_id)
  → enqueue_job("ingest", run_category_revision_job,
                job_id=f"category-revision-{revision_id}")
  → run_category_revision_job(...)
        → build_category_use_cases + build_knowledge_provider_factory
              project taxonomy reconcile + RAG activation
```

The category worker shares the queue with document / version ingest
because its work is also ingestion-shaped — taxonomy reconciliation
re-embeds a project when its category set changes. A failure is
re-raised as `CategoryActivationError("category_worker_failed")` so the
admin UI gets a typed signal.

## Failure semantics

Two failure surfaces exist:

1. **Inside the async coroutine.** `ingest_document` / `ingest_version`
   is responsible for catching failures, recording the error on the
   document / version row (status=`FAILED`, error=...), and committing.
   The worker never crashes silently.

2. **Outside the async coroutine.** RQ-level failures (notably
   `JobTimeoutException` from the death penalty) can be raised outside
   the coroutine frame, bypassing the in-coroutine handler. The worker
   catches these in the sync wrapper (`run_ingest_job`,
   `run_ingest_version_job`) and calls `_mark_doc_failed_sync` /
   `_mark_version_failed_sync`. These open a sync SQLAlchemy session via
   `database_url_sync` and call the repository-layer helpers
   (`mark_document_failed_sync`, `mark_version_failed_sync`) so the
   terminal state is durable even when the async path is dead.

`_mark_*_failed_sync` itself swallows exceptions with
`logger.exception(...)` so it never masks the original RQ failure —
the RQ error is re-raised after the sync write so the queue still
records the job as failed.

## Recovery semantics

Migration **0050_data_ingestion_recovery** introduced the bookkeeping
that lets a crashed job be re-driven safely:

- `kb_versions` rows carry a processing token + state that the worker
  can claim and release atomically.
- A version stuck in `INGESTING` beyond `INGEST_JOB_TIMEOUT_SECONDS`
  is recoverable: a fresh enqueue with the same `job_id` is a no-op,
  and the version's previous attempt's chunks can be cleaned up before
  the retry runs.
- The category worker uses the same pattern: it generates a
  `processing_token` up-front and only writes results whose token
  matches the current claim. A stale claim is silently dropped, so a
  late-finishing previous attempt cannot overwrite the next attempt's
  activation.

## Lifecycle states

`backend/app/project_knowledge/domain/ingestion.py` defines the
ingestion state machine:

| State | Notes |
|---|---|
| `RECEIVED` | Document was uploaded; upload is durable. |
| `STORED` | File bytes persisted to the KB volume. |
| `PARSED` | Text extracted. |
| `NORMALIZED` | Canonicalized (project-owned knowledge mode). |
| `CLASSIFIED` | Project + category assigned. |
| `EXTRACTED` | Sections / entities extracted. |
| `VALIDATED` | Schema + content checks passed. |
| `REVIEW_REQUIRED` | Needs recruiter review. |
| `APPROVED` | Recruiter approved. |
| `PUBLISHED` | Visible to retrieval. |
| `INDEXED` | Embedded and written to pgvector. |
| `FAILED_TRANSIENT` / `FAILED_PERMANENT` | Terminal failure states. |
| `QUARANTINED` | Held aside for inspection. |
| `SUPERSEDED` | Replaced by a newer version. |

`ALLOWED_STATE_TRANSITIONS` is the explicit transition graph the
repository enforces. The runner walks this graph forward and never
skips states, so an admin can replay the document's history.

## Embedding and pgvector

- The `embedding` column is `vector(3072)` (`backend/app/core/vector.py`,
  `EMBEDDING_DIM` constant). The retrieval layer gates ANN on the
  dimension and warns on drift.
- Embeddings are produced by the cached embedder
  (`graph.factories._build_cached_clients`), so a Zalo secret rotation
  never invalidates the embedder.
- Writes go through `kb_chunks` (and the version-specific staging
  table for `kb_versions`) before being promoted to the published
  knowledge base. Promotion is part of the version-ingest path, not the
  document-ingest path — a document that fails never poisons a version
  that is already live.

## What the workers do not do

- **No ingestion on the synchronous chat path.** The webhook and the
  agent never embed; they only read from pgvector via retrieval.
- **No direct LLM calls from the worker.** The composition root resolves
  the LLM clients and embedder through the same cache as the chat
  path, so cost and rate limits apply uniformly.
- **No cross-process pub/sub.** Realtime push is the chat path's
  concern; ingestion completion is observed by the UI via TanStack
  Query re-fetch.
