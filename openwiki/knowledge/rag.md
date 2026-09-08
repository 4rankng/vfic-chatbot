---
type: system
title: Knowledge base, RAG retrieval, and pgvector layout
description: Per-project knowledge documents, the EMBEDDING_DIM schema pin, pgvector halfvec HNSW + exact rerank, the retrieval flow with chunk visibility rules, and the direct-context capacity invariants.
tags: [rag, pgvector, hnsw, halfvec, embedding, retrieval, knowledge-base]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-5a536de57792cef4de4e76e8
    resource: repo://backend/alembic/versions/0016_query_perf_indexes.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-fd1d50d2a6f6710b3af3e2a7
    resource: repo://backend/app/core/vector.py
  - id: openwiki-source-c286d5f65b285f2aeb9ec199
    resource: repo://backend/app/project_knowledge/application/cache.py
  - id: openwiki-source-4789b6c3dfb6ee5ecb3bade4
    resource: repo://backend/app/project_knowledge/application/retrieval.py
  - id: openwiki-source-8d545e2fe4e4e44457d533ae
    resource: repo://backend/app/project_knowledge/domain/canonical.py
  - id: openwiki-source-0d7c742b152218e173ae7243
    resource: repo://backend/app/services/knowledge_base_capacity.py
  - id: openwiki-source-088c334b08efd152af8b021d
    resource: repo://backend/app/services/knowledge_base_service.py
  - id: openwiki-source-8f27a28439eaf3ce0c8244eb
    resource: repo://backend/app/services/retrieval/repository.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

RAG (retrieval-augmented generation) is the spine of the bot's answers.
Per-project knowledge documents are parsed, chunked, embedded, and
written to pgvector. At retrieval time the agent runs an **ANN candidate
selection** over the halfvec HNSW index, then re-ranks the candidates
**exactly** by the full-precision `vector(3072)` cosine distance, so a
candidate that barely missed the ANN top-K can still surface if its exact
ranking is good. Two related concerns live next to RAG: the canonical
knowledge format (which every document is normalized into) and the
direct-context capacity check (which makes sure a one-file "send on every
turn" KB still fits the model's context window).

## Canonical format

`backend/app/project_knowledge/domain/canonical.py` declares:

- `SCHEMA_VERSION = "vfic-knowledge-v1"`
- `FAQ_SCHEMA_VERSION = "vfic-faq-v1"`
- `CANONICAL_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION, FAQ_SCHEMA_VERSION})`

Every published document carries a `metadata.document_metadata.schema_version`
matching one of these values; documents with a missing / mismatching
schema version are filtered out at retrieval time (see "Chunk
visibility" below).

## Embedding dimension is a schema pin

`backend/app/core/config.py`:

```python
EMBEDDING_DIM: int = 3072
```

The constant's docstring is explicit:

> "pgvector stores embeddings as `vector(3072)` (migration 0001) and the
> ANN candidate index is `halfvec(3072) HNSW` (migrations 0014/0016). The
> embedding model's output dimension must equal this value: a mismatch
> breaks both writes (wrong-width vector column) and ANN retrieval, so the
> retrieval layer gates ANN on it and warns on drift instead of silently
> degrading to exact search."

In other words, the embedding model is **not** freely configurable. A
deployment that switches to a model with a different output dimension
must re-embed the entire corpus AND alter the schema (new column type +
new index). The retrieval layer treats a dimension mismatch as a
**one-shot warning + ANN-disabled fallback** rather than a hard failure:

```text
embedding_dim != EMBEDDING_DIM  →  log warning once
                                 →  fall back to exact search
                                 →  retriever.last_match_degraded is set
```

`Settings.embedding_dim` reads from env (`embedding_dim`) and defaults to
3072. The OpenRouter runtime config
(`OpenRouterRuntimeConfig.embedding_dim`) is sourced from this setting.

## pgvector layout

The schema pins two related types:

- `vector(3072)` — full precision, used for storage and for the final
  exact ranking. Inserted via `CAST(:emb AS vector)` using
  `core.vector.vec_literal(v)` (format `[%.8f,%.8f,…]`).
- `halfvec(3072)` — half precision, used by the HNSW ANN candidate
  index on `knowledge_chunks.embedding` and on `memories.embedding` (per
  migrations 0014 and 0016). Querying the index uses
  `c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072))`; the
  final ranking is `c.embedding <=> CAST(:emb AS vector)` (full
  precision).

The `vec_literal` helper is the single point of formatting; the
docstring is explicit that drift across modules was already starting to
bite when this helper was extracted.

## Retrieval flow

`backend/app/services/retrieval/repository.py` owns the SQL. The flow
for `match_documents`:

1. **ANN candidate selection** (when `Settings.rag_ann_enabled` is True
   and `embedding_dim` matches `EMBEDDING_DIM`):

   ```sql
   WITH ann_candidates AS (
     SELECT c.id
     FROM knowledge_chunks c
     JOIN knowledge_documents d ON d.id = c.document_id
     JOIN projects p ON p.id = d.project_id
     WHERE <chunk_visibility(project_clause)>
     ORDER BY c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072))
     LIMIT :candidate_k        -- max(rag_ann_candidates, top_k)
   )
   ```

2. **Exact rerank** of the candidate set:

   ```sql
   SELECT c.id, c.content, c.source_quote, c.summary, c.metadata,
          c.line_start, c.line_end, c.section_path, ktf.filename AS source_file,
          1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity
   FROM ann_candidates ac
   JOIN knowledge_chunks c ON c.id = ac.id
   LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id
   WHERE 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor
   ORDER BY c.embedding <=> CAST(:emb AS vector)
   LIMIT :k
   ```

   `candidate_k` is `max(Settings.rag_ann_candidates, top_k)` so the
   candidate pool is always at least as wide as the requested top-k,
   even when the operator tunes `rag_ann_candidates` below `top_k`.

3. **Fallback path.** When ANN is disabled (operator override or
   dimension mismatch), the same SELECT runs **without** the CTE —
   direct exact scan with `ORDER BY c.embedding <=> CAST(:emb AS
   vector)`. The retriever stamps `last_match_degraded = "ann_disabled"`
   (or the matching reason) into stage_timings so the performance
   dashboard can surface the regression.

`Settings.rag_ann_enabled` is the operator kill switch; `rag_ann_candidates`
controls candidate-pool width; `rag_similarity_floor` (or its per-method
analogue) is the minimum similarity the rerank keeps.

### Chunk visibility

`_chunk_visibility(project_clause)` is the shared WHERE predicate for
both the ANN and exact paths. It enforces:

- `d.status NOT IN ('ARCHIVED', 'FAILED')`
- `c.embedding IS NOT NULL`
- **Category authority** — when `p.category_authority_started IS TRUE`,
  the chunk's `category_revision_id` must match an active
  `knowledge_categories` row for the project.
- **Pre-authority fallback** — when category authority has not started,
  the chunk is visible if its `kb_version_id` matches the project's
  `active_kb_version_id`.
- **Direct-context KBs** — chunks with `chunk_type = 'direct_context'`
  are visible whenever the project has a `DIRECT_CONTEXT` knowledge
  base attached.
- **Metadata filter** — `c.metadata @> CAST(:filter AS jsonb)` when a
  non-empty filter is supplied.
- **Effective dates** — `metadata.document_metadata.effective_from` /
  `effective_to` filter expired / future-dated chunks.

Both queries use this predicate so the visibility rules stay in sync
when they change.

### Memory path

`match_memories(emb, top_k, filter_json)` reads from `memories`. The
shortcut path uses an inline SQL when the only filter key is `chat_id`
(avoiding the SQL function call for the common per-chat lookup). The
generic path delegates to the `match_memories(...)` SQL function ported
verbatim from Supabase at the cutover.

## Project knowledge query surface

`backend/app/project_knowledge/application/retrieval.py:ProjectKnowledgeQueryPort`
declares the provider-neutral surface the graph brain depends on:

| Method | Returns |
|---|---|
| `active_project_ids()` | list of project ids |
| `active_projects_with_card()` | projects with their index card |
| `project_id_by_slug(slug, active_only=False)` | project lookup |
| `match_faq(embedding, top_k=3, project_ids=None)` | FAQ hits |
| `match_documents(embedding, top_k, filters_json, project_ids=None, query_text="")` | document chunks |
| `list_active_projects()` | projects |
| `search_bus_timetable(company, question, limit)` | shuttle entries |
| `job_features_for_project(project_id)` | feature catalog rows |
| `income_summary_for_active_projects()` | aggregate salary stats |

The brain imports only this Protocol. Concrete adapters live in
`backend/app/services/retrieval/` and the composition root
(`graph.factories.build_deps`) wires the per-turn implementation.

## Cache repair

`backend/app/project_knowledge/application/cache.py:ProjectKnowledgeCacheRepairPort`
is a single-method Protocol:

```python
async def repair_knowledge_and_jobs(self) -> None: ...
```

It is invoked after a KB authority bump so the cached knowledge + job
catalog in the running process is refreshed. The actual repair is owned
by the composition layer; the Protocol keeps the brain decoupled from
the concrete adapter.

## Knowledge base lifecycle

`backend/app/services/knowledge_base_service.py` is the standalone
knowledge-base lifecycle service (separate from the versioned KB
ingestion pipeline). It owns:

- `describe(knowledge_base, *, attached_agent_count=None, project_count=None,
  direct_file=None, direct_file_loaded=False)` — projects the row into
  `KnowledgeBaseOut`, counting attached personas + projects and
  hydrating the `KnowledgeBaseDirectFile` (if any) for direct-context
  KBs.
- The lifecycle (create / update / archive) of standalone KBs, with
  audit logging through `record_audit`.
- The `LegacyKnowledgeBootstrap` path used when migrating an old project
  into the new knowledge layout.

## Direct-context capacity

Direct-context KBs (mode `DIRECT_CONTEXT`) deliberately send their sole
text file on every answer, so they must fit alongside the Agent
instructions, retained chat history, and the reserved answer budget of
the currently selected provider/model. **RAG KBs do not use this
module.**

`backend/app/services/knowledge_base_capacity.py` enforces the fit:

- Registered MiniMax model context windows are explicit in
  `_MINIMAX_CONTEXT_WINDOWS` (all current models: 204,800 tokens). An
  unrecognized model is **not assumed to fit** — the resolver raises
  `ConflictError("No context-window limit is registered for the active
  MiniMax model '{model}'")`.
- Reserved tokens: `_BASE_SYSTEM_RESERVE_TOKENS` (6,000) +
  `_CHAT_HISTORY_RESERVE_TOKENS` (12,000) +
  `_CURRENT_MESSAGE_RESERVE_TOKENS` (2,000) +
  `_OUTPUT_RESERVE_TOKENS` (4,000).
- Token estimation: `_CHARS_PER_ESTIMATED_TOKEN = 2` (conservative
  Vietnamese / mixed-text estimate; the provider tokenizer is
  authoritative at request time, so the estimate is validated with
  headroom).
- `DirectContextCapacity.fits` returns `True` only when
  `estimated_input_tokens <= context_window - reserved_tokens`.
- The OpenRouter branch reads `context_window` from a model metadata
  lookup against the OpenRouter `/models` endpoint (cached); an
  unrecognised provider raises
  `ConflictError("The active LLM provider has no direct-context capacity
  resolver")`.

`direct_context_capacity(db)` returns the `DirectContextCapacity` for
the active KB; `require_direct_context_ready(db, knowledge_base)` is the
gate used by the upload path — it raises `ConflictError` if the file
would not fit, so an over-large upload is rejected before the file is
ever stored.

## Why halfvec + exact rerank

- **halfvec HNSW** gives the candidate pool cheaply (half the bytes
  per vector, smaller index, faster graph traversal on the 2 vCPU /
  4 GB droplet).
- **Exact rerank over the candidate set** recovers the precision lost
  by the half-quantization — a candidate that the ANN skipped by a hair
  can still surface when ranked by the full-precision cosine distance.
- The two-step shape keeps the index stable when the operator changes
  `rag_ann_candidates` (broader pool = better recall at marginal cost)
  or `rag_similarity_floor` (tighter threshold = less noise at the
  cost of coverage).

## Operator tunables (env)

- `embedding_dim` — defaults to `EMBEDDING_DIM` (3072); a mismatch
  disables ANN and warns.
- `rag_ann_enabled` — operator kill switch for ANN.
- `rag_ann_candidates` — candidate pool width for the HNSW step.
- `rag_similarity_floor` — minimum reranked similarity a chunk must
  clear to be returned.

Tuning these is a conscious operator decision; the retriever logs the
last-match reason into `stage_timings` so a regression is visible on
the performance dashboard.
