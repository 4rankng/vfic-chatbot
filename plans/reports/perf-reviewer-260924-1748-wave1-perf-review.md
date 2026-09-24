# Wave-1 Performance Review — 16 commits on main

Reviewer: perf-reviewer (code-reviewer role) · 2026-09-24 · HEAD `2f9c130a`

**Verdict: SHIP WITH FOLLOW-UPS.** No production-outage defect at HEAD; all 404 tests across
the touched suites pass (`test_core_cache`, `test_llm_semaphore`, `test_worker_enqueue_utils`,
`test_retrieval_repository_sql`, `test_graph_factories`, `test_knowledge_base_service`,
`test_dashboard_attention`, `test_graph_runner_turn`, `test_graph_tools`, `test_concurrency`,
`test_outbox`, `test_zalo_bot_service`, `test_reconcile_worker`, `test_graph_proactive_turn`).
Three findings need follow-up work (H1–H3); none require reverting HEAD.

Scope reviewed: 41c9c888, a23033a1, f7e86594, 13e78e41, fb9632e2, eb0f5872, 328e5880,
d4107308, 52120dbd, 954633bc, 584b0232, e4290bfd, 17105d7e, 3bd56e7c, 67f63296, e62a323c
against their tickets PERF-02/03/04/06/07/08/09/10/11/12/13/14 in `kanban/DEV_COMPLETED/`.
Integration tests (real Postgres via `tests/integration/conftest.py`) were not run — noted
where that gap matters.

---

## High severity

### H1. fb9632e2 edits the already-applied baseline migration — the fix never reaches production
`backend/alembic/versions/0001_baseline.py:558-573` rewrites `match_memories`'s parameter
from `vector` to `halfvec(3072)`. 0001 is stamped applied on every existing database, so
alembic will never re-run it:

- **Production keeps the old `vector` function** — the commit subject ("so the memories HNSW
  index is usable") is unrealized there for the metadata-filtered slow path; only the app-side
  fast path (17105d7e) delivers the index win.
- **Fresh environments get a different function than production.** `repository.py:190` still
  calls `match_memories(CAST(:emb AS vector), ...)` (pinned by
  `test_retrieval_repository_sql.py::test_memories_sql_function_path_unchanged`). pgvector
  does define `CREATE CAST (vector AS halfvec) ... AS IMPLICIT` (verified in pgvector
  `sql/vector.sql`), so fresh DBs resolve via the implicit cast and work — but nothing in
  this repo's tests executes that path against a live DB, and the `pgvector/pgvector:pg16`
  image tag floats, so the effective extension version is whatever the build pulls.
- The 0001 header's "ported VERBATIM from the live Supabase catalog" claim is now amended —
  the file matches no single real deployment.

Why it matters: silent environment drift on a trust-bearing data path, plus a protected-path
edit (`alembic/versions/*.py` is approval-gated; the user-approved PERF-08 scope described
casting at the app/function level, not rewriting a landed migration). Fix: append a new
migration with `CREATE OR REPLACE FUNCTION public.match_memories(query_embedding halfvec(3072), ...)`
and restore 0001 to its verbatim form. Optionally then cast the call site to halfvec so
query and index expression match exactly.

### H2. The wave's history is not bisectable — mid-range commits contain a turn-path TypeError and a temporary reliability regression
DAG order (oldest→newest): 41c9c888, a23033a1, 328e5880, f7e86594, 13e78e41, fb9632e2,
584b0232, **d4107308**, 52120dbd, eb0f5872, **954633bc**, e4290bfd, 17105d7e, 3bd56e7c,
67f63296, e62a323c, then 8be895b6…fb344ee0, 7e4255b4.

- d4107308 ("perf(runner): refresh only the ownership columns…") also introduces REL-06
  (`claim_send` passing `status=OutboxStatus.SENDING` at `bot_path.py:569`) — but
  `create_pending_outbox` only gains the `status` parameter in 7e4255b4, ~11 commits later.
  Every tree in between raises `TypeError: unexpected keyword argument 'status'` on every
  claimed bot send.
- d4107308 also adds REL-01's `send_partial` handling; 954633bc **removes** it again
  (runner.py and `test_partial_multi_bubble_send_is_send_unknown`), reintroducing the
  partial-delivery→retryable-FAILED double-answer risk mid-history, until fb344ee0 re-lands
  it in sender-side form. HEAD is correct (verified: `zalo_bot_service.py:262-282` flags
  `partial` + ambiguous class; tests pass) but `git bisect` through this range will point at
  the wrong commits during the next incident.
- 13e78e41's config.py diff bundles inert SEC-04/06/08 settings fields ahead of the SEC
  commits that use them; 328e5880's docstring references `_OWNERSHIP_REFRESH_COLUMNS`
  before d4107308 defines it.

Why it matters: incident response and archaeology. Fix: none possible retroactively without
a rewrite the team probably doesn't want — record the hazard, and for future waves land
cross-cutting REL/SEC hunks in their own commits rather than bundling.

### H3. PERF-11 half-done: `bot_suppression_rate` still scans all of `bot_runs`, and the dashboard now mixes 24h and all-time figures
`backend/app/services/dashboard/repository.py:122-131` — `bot_suppression_rate` retains the
unbounded whole-history aggregate (global and recruiter-scoped variants) that PERF-11
targeted; only `bot_run_summary` got the 24h window. Two consequences:

1. Every metrics cache miss still pays the never-pruned `bot_runs` full scan the ticket
   exists to remove.
2. The same dashboard card now shows a 24h success rate (`bot_run_summary`) beside an
   all-time suppression rate. The frontend (`dashboardMetrics.ts:149-165`) prefers the
   backend's non-null all-time `bot_suppression_rate`, so the 24h-derived fallback never
   applies — the mixed windows are what users see.

Fix: window the suppression rate identically, or better, drop the query and derive
`suppressed / (sent + suppressed)` from `bot_run_summary`'s existing counts (one fewer
round trip, one consistent window). The API docstring documents the 24h semantics for the
summary fields; extend it to whichever fields remain all-time after the fix.

---

## Medium severity

### M1. Wave commit subjects describe work their diffs don't contain
- **67f63296** "make the rag cache key order-stable and coalesce by flag only" is
  **tests-only**. The implementation (`sorted(project_ids)` at `knowledge.py:115`, gate
  reduction to flag-only at `:159`) landed in **c3c70a5a (REL-07)** — blame-verified.
  PERF-09/10 are marked dev-completed on the strength of a commit that only pins tests.
- **e62a323c** "self-heal the llm semaphore token list after eviction… release prunes
  refill-race excess" — the diff adds only two `r.persist()` calls; the EXISTS-refill and
  release-side trim pre-date the wave (`a3ebdfd1`, `7659a35c`).

Why it matters: future readers will bisect/attribute to the wrong commits. Fix: commit
message hygiene going forward; optionally a note on the PERF-09/10 cards that the
implementation rode in on REL-07.

### M2. Semaphore release-trim race can permanently under-provision the LLM cap
`backend/app/graph/llm_semaphore.py:124-143` — `_release_token` does `RPUSH` then `LLEN`
then pops `delta` in a loop, non-atomically. Two concurrent releasers that both observe
`count > limit` both pop → count ends **below** limit, and a short list is deliberately
never topped up (`_ensure_tokens` refills only a missing key), so the capacity loss is
permanent until the key is manually deleted. Inflated counts are realistic at every deploy:
two processes cold-initializing together (`if not self._initialized` both see `LLEN=0`,
both `RPUSH` limit tokens → 2×limit). Impact: reduced LLM concurrency (queuing/BLPOP
timeouts under load), not an outage. The a23033a1 volatile-lru switch removes the eviction
recreate-race that would most often trigger trims, which lowers the probability further.
Fix: make release a single Lua script (`RPUSH 1; LLEN; if > limit then LTRIM …`) so the
push-and-cap is atomic.

### M3. The Sterbenz equivalence comment in 17105d7e is wrong for the actual floor
`backend/app/services/retrieval/repository.py:220-231` claims the rewrite is exactly
equivalent because `1 - dist` is exact for distances 0.5–1.0. That covers the distance
side, but `SIMILARITY_FLOOR = 0.30` (`repository.py:40`) is below 0.5, so
`max_dist = 1 - 0.30` is **not** exact (`0.30` is not representable). Old predicate
`fl(1-d) >= fl(0.30)` vs new `d <= fl(1-fl(0.30))` diverge on a ~1-ulp window
(~5.6e-17) at the floor boundary. Practical impact ≈ zero (a row would need distance
within 1e-16 of 0.7; the float16-quantized cached embeddings from 3bd56e7c shift distances
~1e-3, dwarfting this). Rows and order are preserved for all practical inputs. Fix the
comment to claim "equivalent up to one ulp at the floor boundary", or set the floor
comparison entirely on the distance side of the double it controls.

---

## Low severity

- **L1.** `service.py:135-137` dashboard TTL floor silently overrides an operator's
  configured `dashboard_cache_ttl_seconds < 60` with no log line. Documented in the
  comment; acceptable, but a warning log would help ops.
- **L2.** `cache.py:19-26` epoch seeding: the "can never equal a version that existing
  entries were written under" claim requires that a namespace never INCRed more times than
  seconds elapsed since its previous seed (>1 bump/sec sustained). Contrived, but the
  docstring overstates. The two-racers cold-start case is safe: same-second seeds collide
  (identical value); a second-boundary straddle makes the loser's writes unreachable
  misses, never stale serves.
- **L3.** `runner.py` (~1341): `jev_task = asyncio.create_task(...)` has no
  cancellation guard; if `record_bot_pending` or the lead resolution raises before the
  `await jev_task`, the task is orphaned ("Task exception was never retrieved" at GC).
  Cosmetic. Wrap the intervening DB work in try/except that cancels the task.
- **L4.** Audit finding codes (REL-01/REL-06/PERF-02/SEC-*) in code comments and test
  docstrings conflict with the project's stable-artifacts rule. Pervasive pre-existing
  convention (`llm_semaphore.py:74`, `main.py:197`, `config.py:55`…); the wave adds a few
  more (d4107308's runner/bot_path comments, a23033a1's test docstring). Consistency note
  only.
- **L5.** PERF-03 remainder: `ServiceLeadContextAdapter.context()` still re-fetches the
  conversation via `get_by_zalo` for `oa:`-prefixed chats (`service_adapters.py:40`), the
  exact reload the ticket suggested passing in. Small; only the OA path pays it.

---

## Non-issues explicitly cleared (do not re-litigate)

- **PERF-03 column-scoped refresh is safe.** `_OWNERSHIP_REFRESH_COLUMNS`
  (`runner.py:83-92`) is a strict superset of everything `recheck_ownership` /
  `run_start_guard` / `semi_auto_inactive` reads (mode, taken_over_at/updated_at, version,
  bot_lock trio). `conversation_seq` is bumped server-side in the owner branch
  (`bot_path.py:728` `Conversation.conversation_seq + 1`), so the Python-side
  read-modify-write at `:744` only runs in the no-owner branch real claimed turns never
  take. Dropping the contact/`channel_identity` selectin from the refresh only affects
  within-turn display-name freshness — cosmetic. The comment at `bot_path.py:452-459`
  documenting the historical missing-refresh bug is preserved.
- **PERF-08 ANN rewrite preserves rows/order in practice.** Distance expression computed
  once and referenced twice; identical ORDER BY expression; `1 - dist` projection identical
  to the old similarity. The only divergence is the 1-ulp window above (M3). The non-ANN
  fallback branch is deliberately untouched.
- **Memories halfvec quantization has no threshold to flip.** `memory.py:47-60` lists top-5
  with no similarity cutoff; quantization can only reorder near-ties in a bulleted list.
  The `0016` index expression `(embedding::halfvec(3072))` matches the new fast-path
  ORDER BY exactly, including the partial predicate `embedding IS NOT NULL`.
- **PERF-04 catalog invalidation coverage.** `ProjectService` create/update/delete bump
  NS_PREAMBLE (`project/service.py:229,262,276,334`); `ProjectIndexRepo` bumps on card and
  highlight writes; the one gap (legacy `bootstrap_legacy` attach) was found and closed by
  e4290bfd with a regression test. The 600s TTL backstops unknown paths. The direct-file
  text is fetched fresh per turn (never cached), so KB content edits apply immediately.
  Corrupted cache payloads fall through to the DB and re-cache (`factories.py:164-172`).
  UUID/string type round-trips are handled (cache restores UUIDs; non-UUID payloads are a
  clean miss).
- **PERF-07 budget math.** Compose `environment:` overrides `env_file:`; 2×(8+4) +
  7×(4+2) = 66 of max_connections=150; worker-maintenance (13e78e41) carries the 4+2 env,
  matching the "9 processes" comment; `db_pool_timeout` 30→5 is the ticket-sanctioned
  fail-fast.
- **PERF-12 queue wiring.** rq-scheduler jobs carry their queue at schedule time
  (`job.origin` from the `Scheduler(queue_name=...)` constructor), so the maintenance
  scheduler binds correctly even though one `rqscheduler` container fires all jobs;
  `register_unique_tick` cancels by `func_name` across queues, so first boot migrates the
  old followup-registered ticks; the manual trigger (eb0f5872) matches the scheduler queue;
  depth bounds (followup 50, maintenance 20) default-on with 0-disable; worker-maintenance
  has no compose profile gate, so deploys start it; `stop_grace_period: 180s` covers a
  mid-sweep SIGTERM.
- **Cross-commit: volatile-lru × PERSIST × EXISTS-refill.** Under volatile-lru the no-TTL
  keys (both semaphore lists, `cachever:*`) are unevictable, `PERSIST` defends a stray TTL,
  and the EXISTS-refill covers an operator reverting to allkeys-lru. Layered correctly.
  No unbounded no-TTL Redis population was found that could OOM the 256mb budget under
  volatile-lru (embed/RAG/semantic/ratelimit/singleflight keys all carry TTLs).
- **Cross-commit: flush-on-miss generations × cache keys.** `rag:knowledge:*`,
  `preamble:direct_context_catalog:*` all embed their namespace version, so a lost counter
  makes the whole namespace miss once and re-seed consistently; embed keys are
  content-addressed (no version) and unaffected — correct.
- **PERF-13 payload handling.** Legacy JSON-array entries miss cleanly
  (`_unpack_vector`'s `isinstance(payload, str)`), corrupt base64 misses, empty vectors
  miss; key includes provider/model/dim so a dim change re-keys; `normalize_query` shared
  with the answer cache; the embedder still receives the raw query; no message content in
  keys or logs.
- **954633bc overlap safety.** Jev port is HTTP-only on its own client; the shared
  AsyncSession still sees one coroutine at a time (DB work sequential); pending-row write
  still precedes Jev resolution, so failure semantics are unchanged; `profile_name` is
  bound before task creation.
- **Constitution.** No PII/message content in new logs (ids, keys, limits only);
  conventional commit subjects without ticket IDs; the 16 commits touch backend only;
  protected-path edits are confined to the user-approved PERF-02/07/12/08 scopes — except
  the migration-edit route of fb9632e2 (H1), which was inside the approved ticket's
  behavior but the wrong mechanism.

## Test adequacy

- `test_ownership_refreshes_are_column_scoped` pins the **call shape** (refresh called
  twice with the constant), not the invariant that the constant covers everything the
  recheck reads — deleting a column from the list keeps it green. A test asserting the
  constant ⊇ the attributes `recheck_ownership` reads (or an integration takeover test
  through a real session) would pin the invariant.
- PERF-08's tests are SQL-string characterizations (no live DB). Given no integration test
  executes `match_memories` at all, the H1 drift is invisible to CI by construction.
- Takeover suppression tests use stubs (`owned=False`); behavior through the real
  `BotConversationState.recheck_ownership` + real refresh is exercised only by
  `test_concurrency.py:641-653` at the unit level.

## Recommended actions

1. Append a new migration restoring a single `match_memories` definition everywhere;
   revert 0001 to verbatim (H1).
2. Window or derive `bot_suppression_rate` from `bot_run_summary`; document the final
   window semantics (H3).
3. Atomic Lua release for the semaphore (M2) — small, closes the only standing
   concurrency gap on the token list.
4. Correct the Sterbenz comment (M3) and optionally the cache.py docstring (L2).
5. Process notes for the lead: commit-subject/diff mismatches (M1), mid-history TypeError
   (H2), audit codes in comments (L4).
6. Optional follow-ups: `active_turns` index on `conversations(bot_locked_until)`; pass
   the loaded conversation into the `oa:` context path (L5); cancel-guard the Jev task (L3).

Status: DONE

Summary: HEAD is shippable — behavior preservation holds on every dimension the tickets
named, all 404 touched-area tests pass, and the cross-commit layering (volatile-lru ×
PERSIST × refill, flush-on-miss generations, pool budget vs maintenance topology) checks
out. Three follow-ups before this wave is called clean: the landed-migration edit that
never reaches prod (H1), the unbounded mixed-window suppression rate (H3), and the
non-bisectable history with a mid-range turn-path TypeError (H2) as a recorded hazard.
