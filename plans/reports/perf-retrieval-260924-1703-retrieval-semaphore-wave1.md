# perf-retrieval — retrieval/semaphore wave 1 (PERF-08 app half, PERF-09, PERF-10, PERF-13, PERF-02 code half)

Date: 2026-09-24. Author: perf-retrieval teammate. Scope: the five assigned
tickets, app-code halves only; all changes uncommitted in the shared tree.

## Outcome

All five tickets are implemented in app code and verified. Four retrieval-side
tickets (PERF-08, PERF-09, PERF-10, PERF-13) are complete in the app half;
PERF-02's code half is complete but was merged on top of a concurrent REL-02
async-Redis conversion of the same file by another teammate, and I repaired one
defect in that merge (below). Narrow suites: 115 passed, 0 failed across
semaphore, graph tools, retrieval SQL shape, ANN gate, FAQ floor, FAQ bypass,
turn deadlines, and conversation sort. Ruff clean on every file I touched.

## What changed

### PERF-08 (app half) — backend/app/services/retrieval/repository.py

The ANN branch of `_match_document_vector_rows` computes the exact 3072-dim
distance ONCE per candidate row: the outer query is now `SELECT ..., 1 - dist
AS similarity FROM (...) scored WHERE dist <= :max_dist ORDER BY dist LIMIT :k`,
with `:max_dist = 1 - SIMILARITY_FLOOR`. Candidate selection in
`ann_candidates` keeps the halfvec cast so the 0016 index expression still
matches. The memories fast path (chat-id-only filter) now casts to
`halfvec(3072)` on both sides of `<=>` so its query expression matches
`memories_embedding_halfvec_hnsw_idx`; the SQL-function slow path still binds
`match_memories(...)` with the vector cast, unchanged.

Why it is behavior-preserving: candidate selection, the visibility predicate,
the projection, and the LIMITs are untouched. The distance subquery evaluates
the identical expression `c.embedding <=> CAST(:emb AS vector)` once instead of
three times. Floor semantics are bit-identical: over cosine distances in
[0.5, 1] the `1 - dist` subtraction is exact (Sterbenz lemma), so
`1 - dist >= 0.30` and `dist <= 0.70` include exactly the same rows, and
ordering by `dist` is order-isomorphic to ordering by `1 - dist`. The memories
fast path does change the precision of `similarity` from float32-vector to
halfvec — that is the ticket's sanctioned index-matching change; per-chat
memory ranking shifts only at fp16 near-ties, and `search_user_memory` renders
similarity at two decimals.

### PERF-09 — repository.py + backend/app/graph/tools/knowledge.py

`active_project_ids()` gained `ORDER BY p.id`. `search_knowledge` now sorts the
resolved `project_ids` in Python before the digest, so key determinism no
longer depends on any single query's ordering. Cache keys become stable across
heap rewrites, plan flips, and future port changes. No observable behavior
change beyond key stability.

### PERF-10 — backend/app/graph/tools/knowledge.py

Dropped `and project_ids is None` from `coalesce_enabled`; the gate is now only
`getattr(s, "singleflight_enabled", False)`. The single-flight key is the full
cache key (query + now-sorted project scope + knowledge version), so scoped
lookups coalesce safely. `singleflight_enabled` still defaults to False in
config (protected path, untouched).

### PERF-13 — backend/app/graph/tools/_shared.py

`_cached_embed` hashes `normalize_query(query)` (imported from
`app.graph.cache_key` — reuse, not duplication; cache_key.py itself needed no
change) so case, Unicode form, and whitespace variants share one key, and it
stores the vector as base64-packed float16 via stdlib `struct`/`base64`
(~6 KB raw / ~8 KB encoded vs ~60 KB JSON for 3072 dims). `_unpack_vector`
returns None on any non-string or corrupt payload, so live old-format JSON
entries simply miss once and repopulate. Packing is wrapped so an
out-of-float16-range vector cannot fail a turn (the cache-must-never-break-a-turn
invariant); embeddings are unit-normalized, so this is defensive only. The
embedder still receives the raw query. Note the key format change itself makes
every old key cold once — same one-time repopulation as the format change.

### PERF-02 (code half) — backend/app/graph/llm_semaphore.py

`_ensure_tokens` self-heals after eviction while keeping the concurrency cap
honest. Deliberate deviation from the ticket sketch, with reason:

- The sketch ("on every acquire, if llen < limit, re-register") would destroy
  the cap under saturation: when all 8 tokens are checked out, llen is 0, so
  every new acquire would push 8 fresh tokens — the semaphore loses its cap at
  the exact moment it exists (provider 429 storm, 2 vCPU box). Shortage is
  indistinguishable from saturation without held-count tracking, so refill is
  instead gated on the MISSING KEY (EXISTS), which is eviction-specific.
- Shipped behavior: first acquire per process registers via LLEN+RPUSH as
  before (fast path preserved); afterwards every acquire pays one cheap EXISTS
  and recreates the full list only when the key is gone. A present-but-short
  list (saturation) still raises LLMThrottled with no refill.
- Release-side trim: a concurrent recreate can leave more tokens than the
  limit (bounded by holders-at-eviction × processes; a full Redis restart can
  over-fill once), so `__aexit__` prunes `llen > limit` excess back to the cap
  (tokens are interchangeable). Excess is transient and drift-logged.

## Concurrency incident on the shared file

Mid-task the REL-02 teammate converted `llm_semaphore.py` and its tests to the
async Redis client on top of my half. Their conversion had `r = await
get_redis()` — but `get_redis()` is a sync accessor returning the aioredis
client (see `app/core/redis.py`, and cache.py's `await get_redis().get(key)`),
so the await would raise TypeError at runtime, get swallowed by the broad
except, and silently disable token registration AND release (permanent token
leak → deployment-wide throttle after limit calls). I removed the two awaits on
the accessor only. The teammate subsequently iterated again and settled on the
sync client with all token bookkeeping (ensure + release, including my trim)
dispatched to worker threads via `asyncio.to_thread`/executor — my self-heal
structure, recreate log, trim, and tests carried through intact, so the
accessor fix was superseded by their final form and no longer needed.

## Scope addition (user-approved): token keys are TTL-free

Per the lead's follow-up: registration writes now call `PERSIST` on the token
key in both the first-registration and the eviction-recreate branches, so the
deployment's `volatile-lru` switch (which only evicts TTL'd keys) can never put
`llm_sem_tokens` / `llm_embed_sem_tokens` back in the eviction blast radius
even if something else sets a TTL on them. RPUSH alone never sets a TTL, so
this is a defensive guarantee rather than a behavior change; a new test
assertion pins that registration persists the key.

## Commit record (standing order, one commit per ticket)

- `17105d7e` perf(retrieval): compute the ann distance once and match the
  halfvec index — repository.py + tests/test_retrieval_repository_sql.py.
- `3bd56e7c` perf(graph): hash the normalised query and store cached embeddings
  packed — _shared.py.
- `67f63296` perf(graph): make the rag cache key order-stable and coalesce by
  flag only — test_graph_tools.py suite; NOTE the knowledge.py source edits
  (sort + flag-only gate) had already been swept into the REL-07 teammate's
  commit `c3c70a5a`, which committed the shared file while my edits were
  uncommitted in it; the worktree state was verified identical to HEAD
  afterwards, and my test commit pins the behavior either way.
- `e62a323c` perf(graph): self-heal the llm semaphore token list after
  eviction — persistence delta only; the self-heal body had likewise been
  swept into the REL-02 teammate's commit `7659a35c` (shared file), and this
  commit adds the TTL-free registration on top.
- All six of my files verified clean against HEAD after committing; narrow
  suites re-run green on the committed state (29 semaphore + 67
  retrieval/graph-tools = 96) and ruff clean.

## Test evidence

- Narrow (run last, final state): 115 passed — test_llm_semaphore (26, incl.
  5 new self-heal/trim tests), test_graph_tools (45, incl. 6 new: cache-key
  order-insensitivity, scoped/unscoped/disabled single-flight gate, embed-cache
  round-trip, legacy-payload miss, normalised-key sharing + packed store),
  test_retrieval_repository_sql (4, new file pinning distance-computed-once,
  memories halfvec cast, slow path unchanged, ORDER BY p.id), plus the
  pre-existing ann-gate, faq-floor, faq-bypass, turn-deadlines, and
  conversation-sort suites.
- `.venv/bin/ruff check .` — all checks passed.
- Full unit lane `.venv/bin pytest -m "not integration"`: ran twice
  (2347 passed / 41 failed; 2347 passed / 41 failed second run). All 41
  attributed to concurrent teammate work or load, none to my files:
  - test_parallel_tools: sleep-based timing assertions failing only under
    concurrent full-lane runs; 24/24 pass in isolation.
  - test_metrics_capture / test_runtime_surface_inventory:
    `provider_boundary` expected 122 vs actual 121 — git shows the removal is
    in `backend/app/workers/reconcile_worker.py` (another teammate's file; the
    reviewed snapshot needs their update).
  - test_architecture_boundaries: frontend atomic-crm boundary violations from
    the dashboard teammate's new files.
  - test_zalo_bot_service: SendResult error_class mid-refactor (zalo teammate).
  - test_semantic_cache failed in the first run and passed in the second —
    in-flight edits by another teammate.

## Deferred / gated halves (not done, by instruction)

- Alembic: the `match_memories` SQL function (0001_baseline.py) still casts to
  `vector`; the matching halfvec cast is an approval-gated migration edit.
- docker-compose `volatile-lru` + no-TTL for `llm_sem_tokens` /
  `llm_embed_sem_tokens` / `cachever:*` — deployment-gated; compose untouched.
- `hnsw.ef_search` unchanged; follow-up with scripts/eval_retrieval.py
  measuring recall vs latency before any raise.
- `singleflight_enabled` stays False; enabling is an ops decision after a
  gold-set check (await_result timeout 8.0 sits within the turn budget).
- `embedding_cache_ttl_seconds` (86400) unchanged — config path, untouched.
- Excess-token trim after a Redis-restart over-fill is per-release and
  transient; no persistent rebalancing was added (KISS).

## Unresolved questions

1. Confirm with the REL-02 teammate that the accessor fix (drop `await` on
   `get_redis()`) is folded into their change rather than re-overwritten.
2. Does the team want the snapshot test
   (test_runtime_surface_inventory) updated for the reconcile_worker change by
   the owning teammate before this wave commits?
3. Should `match_faq`'s and the exact-path's own 3× distance expressions get
   the same once-only treatment as the ANN path (small, same pattern), or is
   that deferred with ef_search to the measurement-driven follow-up?
