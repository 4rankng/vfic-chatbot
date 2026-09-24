"""Performance + architecture tickets."""

TICKETS = [
    # ------------------------------------------------------------------ perf
    dict(
        id="PERF-01",
        column="QA_TESTED",
        title="Installation authority is re-derived from scratch 2–3× per turn",
        sev="high",
        area="performance",
        labels=["performance", "reliability"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`resolve_active()` runs the full authority derivation — state, revision, manifest "
            "validation, template checksums, configured integrations, persona version, case workflow "
            "version, active KB vector — and only then consults the fingerprint cache, so the cache "
            "short-circuits the final assembly rather than the queries. The graph then calls it 2–3× "
            "per turn plus once per inbound webhook."
        ),
        evidence=[
            "`backend/app/services/installation/service.py:523` — `resolve_active()` runs `get_state()` → `get_revision()` → `db.get(InstallationManifestValidation)` → `_validation_is_current(...)` → `active_kb_vector()` → `_active_context(...)`, and only at `:560` consults `get_cached_fingerprint`.",
            "`backend/app/services/installation/service.py:797-864` — `_validation_is_current` adds `template_checksums` and `configured_integrations` SELECTs plus `get_persona_version` and `db.get(CaseWorkflowVersion)`; the `select()` statements hit the DB even on a warm session (only `db.get` benefits from the identity map).",
            "`backend/app/graph/runner.py:1162` — `runtime_stamp_is_current`; `:1188` and `:1202` — `resolve_active_policy`; `:580` — `_authority_gate` reaches `resolve_active_policy` on its short-circuit paths.",
            "`backend/app/api/webhooks.py:57` — `_runtime_authority_or_inactive` pays the same derivation once per inbound webhook; `backend/app/composition/conversation_messaging.py:40` does so on the inline web-chat path.",
        ],
        impact=(
            "~11–13 DB round trips and 4–6 Redis GETs per turn [EST] — roughly 25–35% of all turn "
            "queries — all serial and all before the LLM starts. On a 2 vCPU box sharing one Postgres "
            "this consumes most of `sla_seconds=10` and `soft_fallback_remaining=2.0`, the FAQ and "
            "side-lookup budgets the deadline logic depends on."
        ),
        fix=(
            "Make it cache-first and resolve once per turn: (a) have `resolve_active()` read "
            "`get_cached_fingerprint` — or a new lightweight `installation_state.authority_generation + "
            "active_revision_id` read, one query — before the full derivation, paying the validation "
            "path only when the version/identity changed or the cache entry is absent; (b) compute it "
            "once in `run_turn` and pass the resolved policy into both the stamp check and "
            "`_authority_gate` via a per-turn memo on `BotRunState`/`GraphDeps`; (c) keep "
            "`invalidate_installation_cache()` (`service.py:922`, bumped on activate/resume/rollback) "
            "as the correctness gate so a cutover is still observed on the next turn. A too-sticky memo "
            "could serve authority one turn too long, so bound it with the version counter plus a short "
            "TTL."
        ),
    ),
    dict(
        id="PERF-02",
        column="QA_TESTED",
        title="`allkeys-lru` Redis can evict the LLM semaphore token list and suppress every turn",
        sev="high",
        area="performance",
        labels=["performance", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Redis runs `--maxmemory-policy allkeys-lru`, so every key is an eviction candidate, "
            "including `llm_sem_tokens`. The semaphore registers its tokens once per process and never "
            "re-checks, and the largest key population is the embedding cache, which stores ~60 KB "
            "JSON float arrays."
        ),
        evidence=[
            "`backend/docker-compose.yml` (redis service) — `--maxmemory 256mb --maxmemory-policy allkeys-lru`, so `llm_sem_tokens` and `cachever:*` are evictable.",
            "`backend/app/graph/llm_semaphore.py:60-75` — `_ensure_tokens()` returns immediately once `self._initialized` is true (set on the first acquire in the process); nothing re-registers tokens after startup.",
            "`backend/app/graph/tools/_shared.py:22-36` with `backend/app/core/config.py:196` — one JSON embedding per unique query, TTL 86400; a 3072-dim float vector as JSON ≈ 60 KB, so ~4 300 entries fill 256 MB, and entries are LRU-refreshed on read [EST].",
            "`backend/app/core/cache.py:38-46` — `cache_version()` returns `\"1\"` when the key is missing, so an evicted `cachever:knowledge` counter resets the namespace instead of invalidating it (RAG 300 s, semantic 1800 s, system prompt 600 s, installation fingerprint 600 s).",
            "`backend/app/workers/chatbot_worker.py:503` — a turn that raises `LLMThrottled` is recorded SUPPRESSED.",
        ],
        impact=(
            "Outage: if `llm_sem_tokens` is evicted, `BLPOP` returns `None` after "
            "`llm_acquire_timeout_seconds=1.5`, `__aenter__` raises `LLMThrottled`, and nothing is sent "
            "to any candidate until every web and worker process restarts — no process self-heals "
            "because `_ensure_tokens` is once-per-process. Token leak: `SimpleWorker` runs jobs "
            "in-process, so an OOM-killed job never reaches `__aexit__`; 8 such deaths with "
            "`llm_concurrency_limit=8` is a permanent deployment-wide throttle. Stale data: counter "
            "eviction makes old `v{n}` entries live again rather than flushing them."
        ),
        fix=(
            "Switch to `--maxmemory-policy volatile-lru` and give `llm_sem_tokens`, "
            "`llm_embed_sem_tokens` and `cachever:*` no TTL — that alone removes the outage class; make "
            "`_ensure_tokens()` run on every acquire when `llen < limit` (a cheap `LLEN`, or a Lua "
            "script that acquires or refills); shrink the embedding payload ~10× by storing packed "
            "float16/base64 instead of JSON floats; write `cachever:*` with a long TTL and treat a "
            "miss as a full flush rather than a reset to `\"1\"`."
        ),
        notes=(
            "Perf finding 8 (blocking synchronous Redis on the event loop, including this semaphore's "
            "release in `llm_semaphore.py:171-190`) is covered by **REL-02**; not duplicated here."
        ),
    ),
    dict(
        id="PERF-03",
        column="QA_TESTED",
        title="Conversation state is re-loaded 3× per turn, each load cascading 3–4 SELECTs",
        sev="high",
        area="performance",
        labels=["performance", "reliability"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "A turn loads the `Conversation` row, then issues two full `db.refresh(conv)` calls whose "
            "only consumers are a pure-Python ownership recheck and a conditional SQL UPDATE that is "
            "already its own authority. Each load cascades into the `contact` and `channel_identity` "
            "`selectin` relationships."
        ),
        evidence=[
            "`backend/app/graph/runner.py:1149` — `svc.get(uuid)` → `backend/app/services/conversation/repository.py:60-61` `db.get(Conversation, id)`.",
            "`backend/app/graph/runner.py:1213` and `:1036` — `await deps.db.refresh(conv)`, the second inside `_claim_and_dispatch`.",
            "`backend/app/models/conversation.py:122-125` — `contact` and `channel_identity` are `lazy=\"selectin\"`; `backend/app/models/contact.py:31-33` — `Contact.channel_identities` is also `selectin`.",
            "`backend/app/services/conversation/bot_path.py:452-471` — `recheck_ownership` is pure Python over the refreshed columns; `:533-557` — `claim_send` is a conditional SQL UPDATE whose `WHERE EXISTS` is the authority, so the refresh adds no correctness.",
            "`backend/app/workers/reconcile_worker.py:107` — the sweep pays the same cascade per candidate (up to `reconcile_batch_size=50`); `backend/app/recruitment/infrastructure/service_adapters.py:44` reloads the conversation again for the `oa:` lead path.",
        ],
        impact=(
            "~9–12 SELECTs per turn for ownership bookkeeping alone [EST] — about 25% of turn queries "
            "— each also paying the `pool_pre_ping` liveness ping when a new checkout is required. The "
            "same cascade is what makes the reconcile sweep and the lead-adapter reload expensive."
        ),
        fix=(
            "Replace both `refresh(conv)` calls with a column-scoped refresh — "
            "`await deps.db.refresh(conv, [\"version\", \"mode\", \"status\", \"bot_lock_owner\", "
            "\"bot_locked_until\", \"bot_lock_heartbeat_at\"])` — or a single scalar `SELECT` used by "
            "the recheck and the claim; do not re-fetch the contact selectin (`_contact_display_name` "
            "and the outbox channel/recipient reads use the first load). Pass the already-loaded "
            "conversation into the lead adapter instead of `get_by_zalo`. The comment at "
            "`bot_path.py:452-459` records that a missing refresh previously caused post-takeover "
            "sends, so validate against the takeover tests."
        ),
    ),
    dict(
        id="PERF-04",
        column="QA_TESTED",
        title="Direct-context lane runs an uncached full-KB scan every turn and re-sends the whole KB as prompt",
        sev="high",
        area="performance",
        labels=["performance"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`_DirectContextAdapter.resolve()` executes an uncached, unlimited join over every active "
            "project and loads the `normalized_text` TEXT column for all of them, on every turn whose "
            "route is not `vacancy_listing`. The capacity guard then re-selects the same row and "
            "re-tokenises the full text, and the whole text is sent as the system prompt."
        ),
        evidence=[
            "`backend/app/graph/factories.py:120-135` — `_DirectContextAdapter.resolve()` joins Project/KnowledgeBase/KnowledgeBaseDirectFile, `WHERE Project.is_active`, `order_by(Project.name, Project.id)`, with no cache and no LIMIT; invoked from `backend/app/graph/runner.py:1392`.",
            "`backend/app/models/knowledge.py:209` — `KnowledgeBaseDirectFile.normalized_text` is TEXT, loaded for every active project into the ORM identity map for the life of the turn.",
            "`backend/app/services/knowledge_base_capacity.py:74-88` — `require_direct_context_ready` re-`SELECT`s the same DirectFile and re-runs `_estimate_tokens` over the full text.",
            "`backend/app/graph/direct_context.py:191-215` — `build_direct_system` embeds the whole text (docstring: never truncates the KB text), sent as the system prompt at `backend/app/graph/runner.py:527`.",
            "`backend/app/services/ingestion/limits.py:26` — `MAX_NORMALIZED_TEXT_BYTES = 10 MB`, while the capacity guard only fails above ~1 M tokens (`backend/app/services/knowledge_base_capacity.py:24-30`).",
        ],
        impact=(
            "One uncached full-table scan plus a full-text column load per turn, a duplicated file read "
            "and O(n) token count, and — for a DIRECT_CONTEXT KB — the entire KB re-sent as prompt "
            "tokens on every LLM call. Cost and latency scale linearly with KB size until the ~1 M-token "
            "guard trips: at `llm_cost_per_mtok_input=1.0` a KB near the ceiling is on the order of "
            "$0.10 per call [EST], and it is also the largest per-turn allocation on a 4 GB box."
        ),
        fix=(
            "Cache the matching projection (slug, name, aliases, knowledge mode) in Redis under the "
            "existing `NS_PREAMBLE` namespace — it changes only on project edits that already bump that "
            "version (`backend/app/services/knowledge/project_index_repository.py:53,85`) — and keep "
            "the `normalized_text` load for the focused project only, via `defer`/`load_only` or a "
            "second targeted query. Fold the capacity check into that single query and cache the "
            "computed `estimated_input_tokens` alongside the file checksum. The prompt-shape/size "
            "question is a prompt-policy change and needs the `AGENTS.md` approval gate — flag it "
            "rather than change it."
        ),
    ),
    dict(
        id="PERF-05",
        column="QA_TESTED",
        title="No provider prompt/prefix caching is exploited on any LLM call",
        sev="high",
        area="performance",
        labels=["performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Nothing in the LLM path sets a provider cache hint: the only `extra_body` in the codebase "
            "sets reasoning effort, and the chat builders pass no cache parameters. The static "
            "preamble is therefore re-billed at full input price on every turn."
        ),
        evidence=[
            "Repo-wide search for `cache_control` / `prompt_cache` / explicit cache markers returns nothing in `backend/app`; the only occurrence of caching in the LLM path is *reading* the counter — `backend/app/graph/clients.py:1106` (`metrics[\"cached_tokens\"] = ... usage.cached_tokens`) and `backend/app/graph/usage.py:40-60`.",
            "`backend/app/graph/clients.py:1485-1488` — the only `extra_body` in the codebase, and it sets only reasoning effort.",
            "`backend/app/graph/clients.py:1403-1499` — `_minimax_chat`/`_openrouter_chat` set `max_retries=0` and no cache parameters.",
            "`backend/app/graph/clients.py:722` — message order is already prefix-friendly (system first, then prefetched evidence, then `HumanMessage`), so nothing structurally blocks it.",
            "`backend/app/graph/context.py:105-160` — the static preamble (persona + active-product index + retrieval/private-context rule blocks) is what is re-sent unchanged every turn.",
        ],
        impact=(
            "The static preamble — and for direct-context KBs the entire KB — is re-billed at full "
            "input price on every turn, while `cached_tokens` is already collected, so the win is "
            "measurable immediately."
        ),
        fix=(
            "Add explicit cache hints for the stable system block (a provider-specific "
            "`cache_control`/`extra_body` marker in `_minimax_chat`/`_openrouter_chat`), keep the "
            "static block byte-identical across turns (it already is — Redis-cached per persona "
            "version), and add a release-gate assertion that `cached_tokens > 0` on the agent lane. "
            "Verify the win from `BotRun.stage_timings.llm_model_ms` plus `cached_tokens` before and "
            "after; prompt content is unchanged, only transport metadata."
        ),
    ),
    dict(
        id="PERF-06",
        column="QA_TESTED",
        title="Turn preamble serialises four independent steps",
        sev="medium",
        area="performance",
        labels=["performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`run_turn` runs the pending record, the lead-gender lookup, the Jev HTTP call and "
            "project/direct-context resolution strictly in sequence, although only Jev consumes "
            "another step's output."
        ),
        evidence=[
            "`backend/app/graph/runner.py:1299` — `record_bot_pending`; `:1338` — lead-gender lookup; `:1346` — `decide_turn`; `:1392` — project/direct-context resolution; then `_resolve_lane`. All sequential; only Jev needs `recent_messages`, fetched at `:1284`.",
            "`backend/app/graph/decisions.py:34-37` — the Jev call is documented at 70–500 ms with a 3.5 s ceiling; `:335` — it uses its own httpx client and touches no DB.",
            "The project/direct-context step at `:1392` is the uncached full-KB scan ticketed as PERF-04, making it the most expensive member of the serial chain.",
        ],
        impact=(
            "~0.5–4 s of avoidable serial latency on every turn before the first LLM token [EST] — on "
            "a 10 s SLA that is the difference between a fast answer and the `soft_fallback_remaining` "
            "path."
        ),
        fix=(
            "`asyncio.gather` the Jev call with `record_bot_pending` (Jev uses its own httpx client "
            "and touches no DB) and with the lead-gender lookup only if that lookup is given an "
            "isolated session (`worker_session_factory()`, already used at "
            "`backend/app/workers/chatbot_worker.py:489`). Keep DB-touching ORM calls sequential "
            "because the shared `AsyncSession` is explicitly not concurrency-safe (documented at "
            "`factories.py:652-657` and `dashboard/service.py:66`)."
        ),
        notes=(
            "Split from a merged ticket. The duplicate lead-resolution half is now PERF-14; the "
            "expensive member of this chain is ticketed as PERF-04."
        ),
    ),
    dict(
        id="PERF-14",
        column="QA_TESTED",
        title="The lead row is re-resolved 2–3× per turn by every adapter that needs it",
        sev="medium",
        area="performance",
        labels=["performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Each adapter that needs lead context calls `_resolve_lead` itself, so the same lookup "
            "repeats two to three times per turn and one redundant `UPDATE` fires when a gender is "
            "inferred."
        ),
        evidence=[
            "`backend/app/recruitment/infrastructure/service_adapters.py:15-26` — `_resolve_lead` (`by_zalo_id`, then `by_contact_id` fallback), invoked by `stored_gender` `:109`, `context` `:37` and `record_inferred_gender` `:113-131`.",
            "`backend/app/graph/runner.py:1338`, `:439` and `:1360` — the three call sites (gender lookup, profile injection, inference write).",
        ],
        impact=(
            "2–6 duplicate lead queries per turn on the hottest path, plus one redundant `UPDATE` "
            "when a gender is inferred. Compounds the write-side race in REL-05."
        ),
        fix=(
            "Resolve the lead once in `run_turn`, put it on the turn object, and pass the row (or a "
            "small fact-only dict) into both adapters while keeping their fallback logic. Read REL-05 "
            "first — it changes the write side of this same path."
        ),
        notes="Split from a merged ticket. The preamble-serialisation half is PERF-06. Related: REL-05.",
    ),
    dict(
        id="PERF-07",
        column="QA_TESTED",
        title="Connection budget exceeds `max_connections=150` and `pool_timeout=30s` outlives the turn SLA",
        sev="medium",
        area="performance",
        labels=["performance", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Every process uses the same 10+10 pool sizing while the compose topology has fewer "
            "processes than the config comment assumes, and the pool wait is three times the "
            "responsiveness SLA. The worst case therefore sits at the Postgres connection ceiling with "
            "no headroom."
        ),
        evidence=[
            "`backend/app/core/config.py:61-63` — `db_pool_size=10`, `db_max_overflow=10`, `db_pool_timeout=30`; `backend/app/core/db.py:18` — `pool_pre_ping=True` adds a liveness ping per checkout.",
            "`backend/app/core/config.py:54-58` — the sizing comment assumes \"2 web + 6 chatbot replicas + followup/ingest/persistence/reconcile/scheduler (~13 processes)\" and tells the reader to raise Postgres `max_connections` to ≥150.",
            "`backend/docker-compose.yml` — `web-blue` + `web-green` (one uvicorn each; `Dockerfile:28` sets `--workers 1`, so `WEB_CONCURRENCY=2` is inert), `worker-chatbot` × 3, `worker-persistence`, `worker-ingest`, `worker-followup` → 8 resident DB-touching processes; `postgres` runs with `-c max_connections=150`.",
            "`backend/app/reporting/infrastructure/performance_dashboard.py:20-24` — opens one session per read, up to 5 concurrent.",
        ],
        impact=(
            "Worst case 8 × 20 = 160 connections against a 150 ceiling before adminer or psql, i.e. "
            "zero headroom [EST]. When a pool is saturated a turn waits up to 30 s for a connection — "
            "three times the whole perceived-responsiveness SLA and past the point where the answer is "
            "useful — while holding the per-chat lock for `bot_lock_ttl_seconds=180`."
        ),
        fix=(
            "Set per-service pool env in compose (web `DB_POOL_SIZE=8`/`DB_MAX_OVERFLOW=4`; each "
            "worker `4`/`2` → 2×12 + 6×6 = 60 worst case, ~40% of the ceiling) and lower "
            "`db_pool_timeout` to ≤5 s so saturation fails fast into the recovery path instead of "
            "silently blowing the SLA. Workers run one job at a time (`SimpleWorker`), so 4+2 is ample."
        ),
        notes=(
            "The comment at `backend/app/core/config.py:54-58` is stale: it sizes for \"6 chatbot "
            "replicas\" while `backend/docker-compose.yml` runs `worker-chatbot` × 3. Fix the comment "
            "in this change so the next sizing decision is not made on a topology that no longer "
            "exists."
        ),
    ),
    dict(
        id="PERF-08",
        column="QA_TESTED",
        title="Retrieval computes the ANN distance three times per row and the memories halfvec index is unused",
        sev="medium",
        area="performance",
        labels=["performance"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The ANN query computes the same distance expression in its projection, its floor "
            "predicate and its ORDER BY, over 200 candidate rows and on the exact `vector` type. The "
            "visibility predicate is applied inside the HNSW CTE as a post-filter, and the memories "
            "path casts to `vector` so its halfvec index can never be used."
        ),
        evidence=[
            "`backend/app/services/retrieval/repository.py:246-266` — `1 - (c.embedding <=> CAST(:emb AS vector))` is computed three times per row (projection, `WHERE ... >= :floor`, `ORDER BY`), over `rag_ann_candidates=200` rows (`backend/app/core/config.py:192`) → ~600 full 3072-dim distance evaluations per retrieval [EST].",
            "`backend/app/services/retrieval/repository.py:155-190` — the entire `_chunk_visibility` predicate (`status NOT IN`, `embedding IS NOT NULL`, a per-row `EXISTS` on `knowledge_categories`, a JSONB `@>` filter, two `#>>`/`::date` effective-date extractions) runs inside the HNSW CTE as a post-filter over `LIMIT :candidate_k`; a filtered HNSW scan has no recall guarantee.",
            "`backend/app/services/retrieval/repository.py:139-165` — `match_memories` (both the fast path and the SQL function at `backend/alembic/versions/0001_baseline.py:558`) casts to `vector`.",
            "`backend/alembic/versions/0016_query_perf_indexes.py:65-73` — `memories_embedding_halfvec_hnsw_idx`, whose own header says the app \"still casts to ``vector``, not ``halfvec`` … the perf win is deferred to that app change\".",
        ],
        impact=(
            "~10–40 ms of avoidable CPU per retrieval [EST], plus a silent recall cliff on scoped or "
            "`effective_from`-filtered data because a selective filter can return far fewer than 200 "
            "candidates. The memories path is a full scan computing 3072-dim distances whenever the "
            "filter is not chat-id-only."
        ),
        fix=(
            "Compute the distance once — `SELECT ..., dist AS similarity FROM (SELECT ..., c.embedding "
            "<=> CAST(:emb AS halfvec(3072)) AS dist FROM ... WHERE <visibility>) s WHERE dist <= "
            ":floor ORDER BY dist` — and use the halfvec cast everywhere so the index expression "
            "matches `0016_query_perf_indexes`; cast both `match_memories` variants to `halfvec`; raise "
            "`hnsw.ef_search` (session-level `SET LOCAL`) or pre-select candidate ids before the "
            "filtered scan if recall on scoped projects matters. The dedupe/rewrite is behaviour-"
            "preserving (same rows, same order formula); the ef_search change is a recall/latency "
            "trade-off to measure with `scripts/eval_retrieval.py`."
        ),
        notes=(
            "Perf finding 16 (dead/unwired subsystems, including the `deadline` parameter "
            "`match_documents` never receives — cited at `backend/app/services/retrieval/repository.py:336-338`) "
            "is covered by **ARCH-03**; not duplicated here."
        ),
    ),
    dict(
        id="PERF-09",
        column="QA_TESTED",
        title="The retrieval cache key is non-deterministic because `active_project_ids()` has no ORDER BY",
        sev="medium",
        area="performance",
        labels=["performance", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`active_project_ids()` returns project ids in heap order, and that list is serialised "
            "straight into the retrieval cache digest, so row order becomes part of every RAG cache "
            "key."
        ),
        evidence=[
            "`backend/app/services/retrieval/repository.py:705-715` — `active_project_ids()` is `SELECT p.id::text FROM projects p WHERE p.is_active AND p.knowledge_base_id IS NOT NULL` with no `ORDER BY`.",
            "`backend/app/graph/tools/knowledge.py:108-110` — the list is fed straight into `_cache_digest(query, project_slug, top_k, project_ids, knowledge_version)`.",
            "`backend/app/graph/tools/_shared.py:16-18` — `_cache_digest` `json.dumps` the list in order, so row order is part of the key.",
        ],
        impact=(
            "A heap-order change — any `Project` UPDATE, an autovacuum rewrite, or a plan flip to a "
            "parallel/seq scan — silently changes every `rag:knowledge:*` key for the whole deployment "
            "at once, producing a mass cache invalidation and a synchronised embed+retrieval stampede "
            "(PERF-10). Purely self-inflicted latency and LLM/embed spend."
        ),
        fix=(
            "Add `ORDER BY p.id` to `active_project_ids()` and/or sort the digest inputs in Python. "
            "One line removes the whole class; no behaviour change is possible."
        ),
    ),
    dict(
        id="PERF-10",
        column="QA_TESTED",
        title="Single-flight coalescing can never engage, so the retrieval stampede is unmitigated",
        sev="medium",
        area="performance",
        labels=["performance", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The single-flight gate requires `project_ids is None`, but `project_ids` is set on every "
            "Zalo turn and every Page-scoped turn, so coalescing is off in production. The feature flag "
            "and the semantic cache are both off as well."
        ),
        evidence=[
            "`backend/app/graph/tools/knowledge.py:149` — `coalesce_enabled = getattr(s, \"singleflight_enabled\", False) and project_ids is None`.",
            "`backend/app/graph/tools/knowledge.py:100-106` — `project_ids` is populated from `active_project_ids()` on every Zalo turn and on every Page-scoped turn, so the condition is false in production.",
            "`backend/app/core/config.py:273` — `singleflight_enabled` defaults to `False`; `backend/app/core/config.py:201` — the semantic cache is off.",
            "`backend/app/graph/tools/knowledge.py:197-200` — the single-flight key is already the full cache key (query + project scope + knowledge version), so scoped lookups are safe to coalesce.",
        ],
        impact=(
            "With 3 `worker-chatbot` replicas, one popular uncached question hit simultaneously is 3 "
            "embeds + 3 vector and lexical retrievals + 3 LLM judgements on a 2 vCPU box, and a KB "
            "version bump (`bump_kb_caches`) invalidates everything at once — the exact thundering herd "
            "the module was built for."
        ),
        fix=(
            "Drop the `project_ids is None` gate: the single-flight key already includes the project "
            "scope and knowledge version, so scoped lookups are safe to coalesce. Enable "
            "`singleflight_enabled` after a gold-set check and keep the existing `await_result` timeout "
            "at ≤ the turn budget; the gate removal itself is orthogonal and safe to ship with the flag "
            "still off."
        ),
        notes=(
            "Perf finding 15 (semantic-cache O(capacity × dim) scan on the event loop and its "
            "Page-scope key hole) is covered by **REL-07**; not duplicated here. Both findings are "
            "gated by the same `semantic_cache_enabled=False` flag at `backend/app/core/config.py:201`."
        ),
    ),
    dict(
        id="PERF-11",
        column="QA_TESTED",
        title="Dashboard runs whole-history aggregates every 30 s over a never-pruned `bot_runs` table",
        sev="medium",
        area="performance",
        labels=["performance", "ops"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The dashboard's summary and latency queries aggregate every `bot_runs` row with no time "
            "predicate, and one counter scans `conversations` on an unindexed predicate. The rows are "
            "never pruned — the retention worker only nulls `decision_trace` — so the cost grows every "
            "month."
        ),
        evidence=[
            "`backend/app/services/dashboard/repository.py:88-99` — `bot_run_summary` does `count(*)`, four `FILTER` counts and `avg(ended_at - started_at)` over all `bot_runs` rows with no time predicate.",
            "`backend/app/services/dashboard/repository.py:203-217` — `bot_run_p95_latency` takes `percentile_cont(0.95)` over 7 days; `:220-228` — `recent_turns_count`; `:194-201` — `active_turns` is `count(*) FROM conversations WHERE bot_locked_until > now()` with no supporting index.",
            "`backend/app/services/dashboard/service.py:54-90` — 13 sequential awaits per cache miss; `:38-39` — the 30 s cache applies only in production.",
            "`backend/app/workers/decision_trace_retention_worker.py:31-46` — only nulls `decision_trace` after 30 days; the row itself (one per turn) persists indefinitely.",
        ],
        impact=(
            "Every 30 s per viewer scope: a full-history aggregate over a monotonically growing audit "
            "table plus an unindexed `count(*)`, all competing with live turns for the same 2 vCPUs. "
            "This is background load that degrades every month."
        ),
        fix=(
            "Bound `bot_run_summary` to a window (`started_at > now() - interval '24 hours'`, covered "
            "by `bot_runs_started_at_idx` from migration 0033) or maintain rolling Redis counters "
            "updated where the `BotRun` is written; merge the five low-cardinality `_scoped_scalar` "
            "counts into one round trip; raise the dashboard TTL to 60 s (the frontend polls at 30 s, "
            "so a 60 s TTL halving the compute cost is invisible). The metric semantics change from "
            "all-time to 24 h and must be reflected in the API field names/labels."
        ),
    ),
    dict(
        id="PERF-12",
        column="QA_TESTED",
        title="Three periodic ticks and the reconcile sweep share a single `followup` worker with no depth bound",
        sev="medium",
        area="performance",
        labels=["performance", "ops", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The reconcile tick, the outbound-dispatch tick and the proactive-nudge tick all register "
            "on the `followup` queue, which has a single replica, and the reconcile sweep also enqueues "
            "to it. Only `webhook_high` has backpressure."
        ),
        evidence=[
            "`backend/app/main.py:97-130` — `run_reconcile_tick` (60 s), `run_outbound_dispatch_tick` (60 s) and `run_proactive_followup_tick` (30 min) all register on `queue_name=\"followup\"`.",
            "`backend/docker-compose.yml` — the `followup` queue gets a single `worker-followup` replica; `backend/app/workers/reconcile_worker.py:67` enqueues to the same queue.",
            "`backend/app/workers/reconcile_worker.py:107-190` — a tick loads up to `reconcile_batch_size=50` full Conversation ORM objects (`backend/app/services/conversation/repository.py:443-513` plus the selectin cascade) then opens a fresh session per candidate.",
            "`backend/app/workers/utils.py:70-78` — backpressure exists only for `webhook_high` (`chat_queue_max_depth=40`); the `followup` queue has no depth bound.",
        ],
        impact=(
            "Head-of-line blocking: a backlog-driven reconcile (the 2026-09-22 class of incident) "
            "occupies the only slot every 60 s, delaying proactive nudges and outbound retries behind "
            "it, and vice versa. With `SimpleWorker` that single worker is the real capacity behind "
            "`sla_seconds` — three concurrent queued turns, not the six the config comment assumes."
        ),
        fix=(
            "Move the reconcile and outbound-dispatch ticks to their own single-replica worker on a "
            "`maintenance` queue, keep proactive nudges on `followup`, and give both a `max_depth`. "
            "Optionally raise `worker-chatbot` to 4 only after PERF-01, PERF-03 and PERF-06 land, since "
            "each replica multiplies per-turn query load. Queue names are already parameterised "
            "(`run_worker.py` takes positional queues)."
        ),
        notes=(
            "Deployment-file change (compose + one registration change) — approval gate. Same stale "
            "`config.py:56` \"6 chatbot replicas\" comment as PERF-07."
        ),
    ),
    dict(
        id="PERF-13",
        column="QA_TESTED",
        title="Embedding cache key is un-normalised and each entry is ~60 KB of JSON",
        sev="low",
        area="performance",
        labels=["performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The embedding cache hashes the raw query string, so case, Unicode form and trailing "
            "whitespace all produce distinct keys, and the value is a JSON array of Python floats. "
            "The answer-cache path already normalises its keys."
        ),
        evidence=[
            "`backend/app/graph/tools/_shared.py:22-36` — key = `embed:{provider}:{model}:{dim}:{sha256(query)}` over the raw query; value = `json.dumps(list[float])`; TTL `embedding_cache_ttl_seconds=86400` (`backend/app/core/config.py:196`).",
            "`backend/app/graph/cache_key.py:47-56` — the answer-cache path already normalises (NFC + lowercase + whitespace collapse).",
            "`backend/app/core/config.py:196` — `embedding_cache_ttl_seconds: int = 86400`, i.e. one entry per distinct raw string for a day.",
        ],
        impact=(
            "`\"Lương bao nhiêu?\"`, `\"lương bao nhiêu\"` and trailing-whitespace variants are three "
            "separate API calls and three ~60 KB Redis values [EST] — which is also what fills the "
            "256 MB budget behind PERF-02."
        ),
        fix=(
            "Normalise with the same `normalize_query()` before hashing, and store the vector "
            "base64-packed as float16 (~6 KB, so ~10× more entries in the same memory and cheaper to "
            "parse). A normalised key cannot change retrieval semantics because the cached vector is "
            "reused only for the identical normalised query."
        ),
        notes=(
            "Shares its packed-float16 remedy with PERF-02 (audit finding 2, recommendation (iii)); "
            "land the two together."
        ),
    ),
    # ---------------------------------------------------------- architecture
    dict(
        id="ARCH-01",
        column="QA_TESTED",
        title="`app/services/ingestion/` is an 18-module subsystem with no production entry point",
        sev="high",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The whole ingestion/template subsystem is reachable only from tests: no API router "
            "exposes it, no worker calls it, and a repo-wide grep for `services.ingestion` inside "
            "`backend/app` returns only intra-package imports."
        ),
        evidence=[
            "`backend/app/services/ingestion/fact_repository.py` — imported only by `backend/tests/test_fact_repository.py:3,16`; `backend/app/services/ingestion/projector.py` and `review_service.py` — only `backend/tests/test_projector_and_review.py:7,15`.",
            "`backend/app/services/ingestion/normalization.py` — only `backend/tests/test_ingestion_normalization.py:5`; `structured_llm_extraction.py` — only `backend/tests/test_structured_llm_extraction.py:6`; `state_machine.py` — only `backend/tests/test_ingestion_state_machine.py:10`.",
            "`backend/app/services/ingestion/template_service.py:155-159` — `TemplateService.preview` has no caller, and the rest of the template cluster (`template_ingestion`, `template_compiler`, `generic_extraction`, `extraction`, `validation`, `limits`, `source_blocks`) is reachable only through it plus three test files.",
            "`backend/app/services/ingestion/classification.py` — its one in-app importer, `extraction.py:29`, is itself dead.",
            "`backend/app/main.py:12-27` — registers 15 routers and none is an ingestion-template router; the only `template` routes in `app/api/` are markdown download endpoints (`knowledge.py:64-79`, `personas.py:140-146`, `projects.py:241-258`).",
        ],
        impact=(
            "~3.5k LOC of unexercised production code that reviewers and agents must reason about, and "
            "it carries the only writers of the structured-fact tables (ARCH-02), which makes the "
            "provenance schema look live when it is not. Any bug in it is invisible to production."
        ),
        fix=(
            "Delete the package, or — if the template-ingestion feature is planned — park it under "
            "`backend/experimental/` outside `app/` so it stops being counted as production surface, "
            "and add the missing API router in the same change that revives it. Do not leave it in "
            "`app/` with test-only callers."
        ),
    ),
    dict(
        id="ARCH-02",
        column="QA_TESTED",
        title="Structured-fact / provenance subsystem is write-only at runtime and the canonical FAQ read path is dead",
        sev="high",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`models/provenance.py`'s twelve tables have writers whose only callers are themselves "
            "unreachable, and their readers are reached only through the dead `chatbot/paths.py`. The "
            "live FAQ path is the legacy chunk-based one, so the schema looks authoritative but never "
            "serves a turn."
        ),
        evidence=[
            "`backend/app/services/knowledge/publishing/publisher.py:69` — `publish_contract` writes the fact tables; its only caller is `backend/app/services/ingestion/recruitment_adapter.py:58`.",
            "`backend/app/services/ingestion/recruitment_adapter.py` — has no non-test importer (grep: only `backend/tests/test_recruitment_adapter.py:4`); `backend/app/services/ingestion/template_ingestion.py:216` is the other writer and is dead via ARCH-01.",
            "`backend/app/services/knowledge/tools/domain_tools.py:117,149,182,244,290` — `get_benefits`/`get_working_hours`/`get_job_requirements`/`get_job_locations`/`get_faq_entry`, whose only caller is the dead `backend/app/services/chatbot/paths.py:95,162`.",
            "`backend/app/models/provenance.py` — 17.7 KB defining `FaqEntry`, `JobBenefit`, `JobRequirement`, `JobLocation`, `WorkingHours`, `WorkingHoursException`, `FieldEvidence`, `ExtractionRun`, `SourceDocument`, `SourceFragment`, none of them reachable from a serving path.",
            "Live FAQ path: `backend/app/services/project/faq.py` → `KnowledgeChunk` rows (`repository.py:202 managed_faq_document`) → `backend/app/services/retrieval/repository.py:475,524`.",
        ],
        impact=(
            "The provenance schema, `publisher.py` and `domain_tools.py` all look authoritative but "
            "never serve a turn. Worse, this is a live correctness trap: a future reader of "
            "`models/provenance.py` will assume `FaqEntry` is the FAQ source of truth and edit the "
            "wrong table."
        ),
        fix=(
            "Decide explicitly. (a) Delete `publisher.py` + `domain_tools.py` + the fact tables and "
            "document the chunk-based FAQ as canonical, or (b) wire `domain_tools.get_faq_entry` into "
            "the FAQ pre-pass at `backend/app/graph/tools/knowledge.py:263-268` and retire "
            "`ProjectFaqService`. Leaving both is the one outcome strictly worse than either. The "
            "remaining provenance tables' deadness is inferred by transitivity through ARCH-01 "
            "[INFERENCE]; option (b) is effort L."
        ),
        notes=(
            "Shares the ingestion cluster with ARCH-01 and the FAQ duplication pair with ARCH-17(b)."
        ),
    ),
    dict(
        id="ARCH-03",
        column="QA_TESTED",
        title="`services/chatbot/{paths,budget,deadlines}.py` is a parallel turn-dispatch implementation that never runs",
        sev="high",
        area="architecture",
        labels=["tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "A second, test-only turn dispatcher sits beside `graph/runner.py`'s inline branching, and "
            "the retrieval time-boxing it describes is unwired: `match_documents(..., deadline=None)` "
            "is never passed a deadline in production, so the budget settings it reads are inert."
        ),
        evidence=[
            "`backend/app/services/chatbot/paths.py:11-13` — its own docstring: \"Today the runner.py inline branching handles fast_lane / faq_bypass / agent; this module formalizes that into named paths so the dispatch is testable in isolation.\"; only caller `backend/tests/test_budget_and_paths.py:10`.",
            "`backend/app/services/chatbot/budget.py` — `TurnBudget`/`CallKind` per-turn caps, imported only by the dead `paths.py:21`.",
            "`backend/app/services/chatbot/deadlines.py:78-79` — `TurnDeadline.from_state` reads `turn_retrieval_budget_seconds`/`turn_rerank_budget_seconds` (`backend/app/core/config.py:266-267`); only caller `backend/tests/test_turn_deadlines.py:23`.",
            "`backend/app/services/retrieval/repository.py:324` — `match_documents(..., deadline=None)`; neither `backend/app/graph/tools/knowledge.py:268` nor `backend/app/services/job_service.py:81` supplies it.",
        ],
        impact=(
            "The retrieval time-boxing described at `deadlines.py:37-42` as an active protection does "
            "not exist in production: a slow vector arm can consume the whole turn budget and only the "
            "RQ-level deadline survives. This is the one finding in the audit with a plausible "
            "user-visible failure mode, not just maintenance cost."
        ),
        fix=(
            "Two options. (a) Delete `paths.py` + `budget.py` + `deadlines.py` and the two config keys, "
            "then document that turn time-boxing is deadline-at-epoch only; or (b) construct "
            "`TurnDeadline.from_state(state, settings)` in `backend/app/graph/runner.py` and thread it "
            "through `GraphRetrievalPort.match_documents`. The report recommends (a) — delete. Do not "
            "keep the module and the unwired call site both."
        ),
        notes=(
            "This is the ticket that covers perf finding 16's time-boxing item (the unwired `deadline` "
            "parameter), per PERF-08."
        ),
    ),
    dict(
        id="ARCH-04",
        column="QA_TESTED",
        title="`graph/fast_lane.py` and the `template` route strategy are unreachable, so every pleasantry costs a full LLM turn",
        sev="high",
        area="architecture",
        labels=["tech-debt", "performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The router still emits a `template` strategy for pleasantries, but nothing consumes it — "
            "`runner.py` states outright that every normal user message reaches the LLM. The templates "
            "and the pleasantry classification are therefore write-only residue that advertises a lane "
            "which cannot fire."
        ),
        evidence=[
            "`backend/app/graph/fast_lane.py:56` — `template_for` is imported only by `backend/tests/test_golden_set.py:25`, `backend/tests/test_graph_decisions.py:24` and `backend/tests/test_persona_voice.py:24`.",
            "`backend/app/graph/router.py:87-93` — still emits `TurnRoute(\"small_talk\", \"template\", reason=\"fast_lane_match\", ...)`; `backend/app/graph/runner.py:355-357` only copies `route.strategy` into timings.",
            "`backend/app/graph/runner.py:1414-1416` — \"Final replies do not use a template fast lane: every normal user message reaches the LLM.\"",
            "`backend/app/graph/ports.py:90` — `TurnDecisions.pleasantry_kind`, populated at `backend/app/graph/decisions.py:281-285` and never read in production.",
            "`backend/app/graph/router.py:29,43` (`TurnStrategy`, `FAST_MODEL_STRATEGIES`) and `backend/app/schemas/bot_run.py:40` (`fast_lane_match`) all still advertise the lane.",
        ],
        impact=(
            "A pleasantry costs a full LLM turn even though `fast_lane.py`'s templates exist and are "
            "voice-guarded by tests, and the `template` literal plus the `fast_lane_match` trace value "
            "mislead anyone reasoning about latency from `decision_trace`."
        ),
        fix=(
            "Two options. (a) Re-enable it in `_agent_turn` with a `route.strategy == \"template\"` "
            "early return calling `template_for(decisions.pleasantry_kind)`, which removes one LLM call "
            "from every greeting; or (b) delete `fast_lane.py`, the `template` strategy and "
            "`pleasantry_kind`. The report presents both and does not state a preference, but it "
            "records the disable at `runner.py:1414-1416` as a deliberate product decision and the "
            "residue as accidental, so (b) is the consistent choice. If the lane is kept, "
            "`FAST_MODEL_STRATEGIES` must drop `\"template\"` since a template route never reaches a "
            "model."
        ),
    ),
    dict(
        id="ARCH-05",
        column="QA_TESTED",
        title="`graph/clients.py` (1626 LOC) holds seven responsibilities and duplicates `graph/grounding.py`",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "One file carries LangChain reasoning-field compatibility, Redis LLM observability, "
            "prefetch heuristics, grounding/authority extraction, provider retry/quota/failover, the "
            "tool loop and the chat factories. The grounding concern is a second implementation of a "
            "module that already exists."
        ),
        evidence=[
            "`backend/app/graph/clients.py:35,49,85` — reasoning-field compatibility; `:139-141,142,158` — Redis LLM observability; `:176-219` — prefetch heuristics; `:254-277,422-443` — provider retry/quota/failover.",
            "`backend/app/graph/clients.py:283,314,363,387,406` — `_active_job_safe_reply`, `_ground_reply`, `_negative_job_authority`, `_matched_job_authority`, `_ground_active_job_reply`.",
            "`backend/app/graph/clients.py:663` — `MiniMaxAgent`; `:1410,1421` — `_chat_for_role`/`_minimax_chat` factories.",
            "`backend/app/graph/grounding.py:108,178` — hallucination stripping and `extract_surfaced_entities` already exist, so concern 4 is an accidental second grounding module rather than a new one.",
        ],
        impact=(
            "Every LLM call path crosses this file. Two owners for reply authority means a grounding "
            "change can be applied to one and not the other, and the file's size is why the graph "
            "import guard is worth so little here."
        ),
        fix=(
            "Natural seam: split concerns 1+2+3+5 into `graph/reasoning_compat.py`, "
            "`graph/llm_observability.py`, `graph/prefetch.py` and `graph/provider_failover.py`; move "
            "concern 4 (`clients.py:283-421`) into the existing `graph/grounding.py` so grounding has "
            "one owner; keep `MiniMaxAgent` + the factories in `clients.py`. Do not split "
            "`MiniMaxAgent` itself — its tool loop is cohesive."
        ),
        notes="F5's grounding half is the same duplication pair as ARCH-17(f).",
    ),
    dict(
        id="ARCH-06",
        column="QA_TESTED",
        title="`services/integration_settings.py` (1208 LOC) mixes crypto, six provider groups and cache invalidation",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "One module holds the AES-GCM credential cipher, six provider resolve/admin-view pairs "
            "each with its own key set, and the cache-namespace invalidation mechanics. The cipher has "
            "no dependency on any provider, and the provider groups share only the storage primitives."
        ),
        evidence=[
            "`backend/app/services/integration_settings.py:264-323` — `IntegrationSettingsCipher` (AES-GCM, `v1:`/`v2:` versioning, AEAD context binding), independent of every provider.",
            "`backend/app/services/integration_settings.py:406,427,759,781` — Zalo; `:460,478,876` — MiniMax; `:494,520,911` — OpenRouter; `:539,574,674` — custom LLM; `:593,615,627` — Jev; `:1012,1036,1059,1086,1150,1188,1194,1204` — Facebook app and per-Page.",
            "`backend/app/services/integration_settings.py:942,705,732,964,996,352` — `_bump_provider_namespaces`, `_write_setting`, `_write_secret`, `record_provider_test_result`, `invalidate_facebook_cache`, `normalize_llm_failover_order`.",
        ],
        impact=(
            "Every provider credential path runs through one 1208-line module, so a change to any "
            "provider's key set is reviewed against the other five and the cipher is reachable from "
            "code that has nothing to do with encryption."
        ),
        fix=(
            "Natural seam: `services/integration_settings/{cipher,providers/{zalo,llm,facebook},"
            "storage}.py`. `IntegrationSettingsService` keeps its public method names (called from "
            "`api/integrations.py`, `graph/factories.py:637`, `workers/persistence_worker.py:74` and "
            "`services/installation/service.py`) and becomes a facade composing the three provider "
            "groups — the same facade pattern already used by `ConversationService` "
            "(`services/conversation/__init__.py:36`)."
        ),
    ),
    dict(
        id="ARCH-07",
        column="QA_TESTED",
        title="`api/integrations.py` (1353 LOC) carries provider business logic, including a raw httpx OAuth POST",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The router holds the Zalo webhook sync policy, a four-layer credential diagnostic that "
            "issues a raw httpx POST to the OAuth token endpoint, the whole Facebook OAuth flow with a "
            "Redis-backed flow store, and schema mapping. None of that is an HTTP concern."
        ),
        evidence=[
            "`backend/app/api/integrations.py:295-310` — a raw `httpx` POST to `https://oauth.zaloapp.com/v4/oa/access_token` inside `test_zalo_oa`, interpreting `error == -14004`.",
            "`backend/app/api/integrations.py:96-121` — `_sync_bot_webhook` pushes the webhook secret to Zalo via `setWebhook` with change-detection policy; `:406-456` — `_probe_and_record` provider probe plus persistence.",
            "`backend/app/api/integrations.py:708-1012` — the Facebook OAuth flow: `_redis:708`, `_fb_callback_url:718`, `_facebook_oauth_coordinator:749` (Redis-backed flow store, `secrets.token_urlsafe` state), token exchange `:859`, `subscribe_app_to_page:964`.",
            "`backend/app/api/integrations.py:1159-1252` — `disconnect_facebook` calls `unsubscribe_app_from_page:1202` inline; `:1238` — `_assignments_out` schema mapping.",
        ],
        impact=(
            "The highest-risk credential flows in the product live in the transport layer, so they "
            "cannot be exercised without HTTP and the raw httpx call bypasses the "
            "`get_integration_http_client` abstraction that the rest of the codebase uses."
        ),
        fix=(
            "Natural seam: the repo already has the right home — `app/integrations/facebook_oauth/`, "
            "whose `application.py:20,32` define the `FacebookOAuthStateStore`/`FacebookOAuthFlowStore` "
            "Protocols. Extract `services/integrations/zalo_diagnostics.py` (the 4-layer OA probe, the "
            "raw OAuth POST and the Bot probe) and `services/integrations/facebook_oauth_flow.py` "
            "(flow orchestration, Redis state, subscribe/unsubscribe); the router then parses the body, "
            "calls the service, maps the domain error and returns the response model. That is also what "
            "lets the raw `httpx` call at `:295` move behind `get_integration_http_client`."
        ),
    ),
    dict(
        id="ARCH-08",
        column="QA_TESTED",
        title="`services/retrieval/repository.py` (992 LOC) implements the whole agent read surface and self-constructs its collaborators",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "One class owns memory match, document hybrid retrieval, FAQ, the project catalog, the "
            "persona body, the bus timetable and job/income reads. Four of its methods construct a "
            "`RecommendationRepository` — and one a `LeadRepository` — inline instead of receiving "
            "them, so the port the graph injects silently instantiates two other services per call."
        ),
        evidence=[
            "`backend/app/services/retrieval/repository.py:161` — memory match; `:201,257,316,405,442` — document hybrid retrieval; `:475,524` — FAQ; `:606,621,643,705,718` — project catalog; `:668` — persona body; `:589,741` — bus timetable; `:899,920,927,960` — job features, income summary, job recommendations, active jobs.",
            "`backend/app/services/retrieval/repository.py:922,933,963,982` — `from app.services.recommendation import RecommendationRepository` inside method bodies; `:935` — `LeadRepository` likewise.",
            "`backend/app/graph/factories.py:856` — the graph injects this as its read-only retrieval port, so each of those calls instantiates a recommendation repository and a lead repository.",
            "`backend/app/project_knowledge/application/retrieval.py:9-25` — `ProjectKnowledgeQueryPort` declares `job_features_for_project` and `income_summary_for_active_projects`, recruitment concerns absorbed by a project/knowledge-owned port because of this coupling.",
        ],
        impact=(
            "The read-only retrieval port the graph injects reaches into two other services per call, "
            "and a project/knowledge-owned port now declares recruitment concerns — the seam is in the "
            "wrong place, which is why the port had to absorb them."
        ),
        fix=(
            "Split into `retrieval/document_repository.py` (`:161-473`), `retrieval/faq_repository.py` "
            "(`:475-583`), `retrieval/catalog_repository.py` (`:606-757`) and "
            "`retrieval/timetable_repository.py` (`:741-897`), and inject `RecommendationQueryPort` "
            "(which already exists at `recruitment/application/ports.py` and is already imported by "
            "`graph/ports.py:20`) instead of importing `RecommendationRepository`. That also lets "
            "`ProjectKnowledgeQueryPort` shed its recruitment methods."
        ),
    ),
    dict(
        id="ARCH-09",
        column="QA_TESTED",
        title="`graph/factories.py` (900 LOC) does five jobs and is grandfathered out of the import guard",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The composition root holds port adapters, LLM builders, a process-wide client cache with "
            "async retirement, Page-scope resolution and `build_deps` plus six shims. The import guard "
            "exempts the file by name, so none of it is checked, although only the client cache "
            "actually needs the `app.models`/`app.services` imports."
        ),
        evidence=[
            "`backend/app/graph/factories.py:103,228,306` — `_DirectContextAdapter`, `_FaqBypassAdapter`, `_RuntimePolicyAdapter`; `:346,360,389,444` — LLM builders.",
            "`backend/app/graph/factories.py:561,577,610,627,708,717` — `_CachedClients`, `_close_client_bundles`, `_schedule_client_retirement`, `_build_cached_clients`, `reset_client_cache`, `aclose_client_cache`.",
            "`backend/app/graph/factories.py:732-757` — Page-scope resolution; `:760-870` — `build_deps`; `:872-900` — six `_build_*` shims.",
            "`backend/tests/test_graph_import_guard.py:35` — exempts `factories.py` by name; `backend/app/graph/factories.py:118-120,744-745` — the `app.models`/`app.services` imports that only concern 3 genuinely needs.",
        ],
        impact=(
            "The guard's exemption is as wide as the file, so the graph's composition root is the one "
            "place where graph↔services edges go unchecked; it is also the least testable part of the "
            "graph."
        ),
        fix=(
            "Extract concern 3 into `graph/client_cache.py` (self-contained, and it already has "
            "`reset_client_cache` as its seam) and concern 1 into `graph/adapters.py`. Then narrow the "
            "exemption at `backend/tests/test_graph_import_guard.py:35` from \"all of factories.py\" to "
            "the one module that genuinely needs it, which materially strengthens the guard."
        ),
    ),
    dict(
        id="ARCH-10",
        column="QA_TESTED",
        title="`api/knowledge.py` calls private service methods, so the cutover guard is enforced at four call sites",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The router calls `KnowledgeService._require_version` and "
            "`KnowledgeService._require_legacy_mutation_allowed` directly, although the service "
            "already runs the same guards inside its own mutation methods. The guard is a precondition "
            "of the mutation, not an HTTP concern."
        ),
        evidence=[
            "`backend/app/api/knowledge.py:129,175,176,397,420` — the router's calls to the two underscore methods.",
            "`backend/app/services/knowledge/service.py:205,253,339,370,476,504,521,542` — the same guards already run inside `ingest_version`/`ingest_document` and the other mutation methods, so the router calls are duplication.",
            "`backend/app/services/knowledge/service.py:652-655` — the cutover rule being guarded (\"Project-owned knowledge is exclusive to its selected mode\").",
        ],
        impact=(
            "The cutover rule is enforced at four call sites instead of one, so any new mutation path "
            "that forgets the underscore call silently bypasses the migration guard."
        ),
        fix=(
            "Delete the two router calls — the private guards already run inside "
            "`ingest_version`/`ingest_document`. If a route genuinely needs to validate before "
            "enqueueing, expose a public `assert_mutable(project_id)` and call that; never the "
            "underscore name."
        ),
    ),
    dict(
        id="ARCH-11",
        column="QA_TESTED",
        title="Over-abstraction: single-implementation facades, a mis-declared Protocol and a test double in production code",
        sev="medium",
        area="architecture",
        labels=["tech-debt", "testing"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Several Protocols and facades have exactly one implementation and no behaviour of their "
            "own, one facade is wired two different ways depending on the caller, a Protocol is used "
            "as a dataclass, and a conformance-suite test double ships in `app/`."
        ),
        evidence=[
            "`backend/app/project_knowledge/application/categories.py:54` — `CategoryUseCases`, seven methods each a bare `return await self._port.<same name>(...)`, typed `object`/`Any`; one implementation (`SqlAlchemyCategoryAdapter`); consumers at `backend/app/api/projects.py:237,251,271,286,327,351,366,384`.",
            "`backend/app/services/knowledge/external_source_sync/__init__.py:355-357` — constructs `CategoryUseCases(KnowledgeCategoryService(db))` directly, bypassing `build_category_use_cases` (`backend/app/composition/project_knowledge.py:50`), so the same facade has two different adapters.",
            "`backend/app/project_knowledge/application/ingestion.py:26` — `KnowledgeIngestionUseCases`, two pure-delegation methods, one implementation; `backend/app/project_knowledge/application/cache.py:8` — `ProjectKnowledgeCacheRepairPort`, one method, one implementation.",
            "`backend/app/capabilities/contracts.py:9` — `CapabilityAdapter` declared as a Protocol whose only \"implementation\" is the frozen dataclass `RecruitmentAdapterDescriptor` (`backend/app/capabilities/recruitment/adapter.py:6`); `adapter_descriptors` is populated at `registry.py:97` and never consumed.",
            "`backend/app/channels/accounts.py:44` — `_StaticChannelAccountResolver`, docstring: \"This double lets the conformance suite exercise active/inactive behavior without a database\".",
        ],
        impact=(
            "Indirection with no behaviour to hide, a facade that resolves to different adapters "
            "depending on the caller, and a test double shipped in production code — all of which make "
            "a reader look for behaviour that is not there."
        ),
        fix=(
            "Delete `CategoryUseCases` and `KnowledgeIngestionUseCases` (call the adapters directly "
            "from the composition root, as `graph/factories.py` already does) and fix "
            "`external_source_sync/__init__.py:355` to go through `build_category_use_cases` in the "
            "same change; convert `CapabilityAdapter` from a Protocol to the dataclass it actually is. "
            "The rule to apply: a Protocol earns its place when a fake exists that changes behaviour "
            "under test, or two implementations are planned in the same change — contrast "
            "`graph/ports.py` and `conversation_messaging/application/outbound_recovery.py::"
            "OutboundRecoveryPort`, which have real fakes."
        ),
    ),
    dict(
        id="ARCH-12",
        column="QA_TESTED",
        title="`services/conversation/bot_path.py` (1118 LOC) carries five responsibilities",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "One file owns identity ensure, the inbound guards, the Redis lock lifecycle, the TOCTOU "
            "send claim, outcome recording, the reconcile sweeps and the proactive path. The lock "
            "family is pure Redis plus model-state logic with no dependency on the send path."
        ),
        evidence=[
            "`backend/app/services/conversation/bot_path.py:70,93,124-186` — identity ensure, creating `Contact` + `ContactChannelIdentity` + `Conversation` atomically.",
            "`backend/app/services/conversation/bot_path.py:187,195,207,258` — inbound guards (`semi_auto_inactive`, `run_start_guard`, `record_inbound`, `escalate_extracted_intent`).",
            "`backend/app/services/conversation/bot_path.py:329,365,392,417` — lock lifecycle; `:452,473` — the TOCTOU send claim.",
            "`backend/app/services/conversation/bot_path.py:560,770,997` — outcome recording; `:799,820` — reconcile sweeps; `:861,966` — proactive outcome and message preparation.",
        ],
        impact=(
            "Five unrelated change reasons share one file, and the module sits on the hot turn path "
            "(PERF-03, PERF-06), so a lock change is reviewed against the send path and vice versa."
        ),
        fix=(
            "Natural seam: `conversation/locking.py` (`:329-451`), `conversation/send_claim.py` "
            "(`:452-559`, `:997`), `conversation/bot_outcome.py` (`:560-798`) and "
            "`conversation/reconcile.py` (`:799-860`). The lock family is the cleanest cut in the "
            "codebase — pure Redis plus model-state logic, no dependency on the send path."
        ),
    ),
    dict(
        id="ARCH-13",
        column="QA_TESTED",
        title="`@lru_cache get_settings()` plus seven import-time settings snapshots; `core/db.py` creates the engine at import",
        sev="medium",
        area="architecture",
        labels=["tech-debt", "testing"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Seven modules capture `get_settings()` at import time, which defeats the standard "
            "`monkeypatch.setenv` + `cache_clear()` remediation, and `core/db.py` binds the production "
            "pool configuration when it is imported."
        ),
        evidence=[
            "`backend/app/core/config.py:469` — `@lru_cache def get_settings()`; snapshots at `backend/app/core/db.py:14`, `core/redis.py:12`, `core/security.py:30`, `realtime/emitter.py:20`, `realtime/socketio.py:34`, `services/conversation/bot_path.py:47` and `main.py:36`.",
            "`backend/app/services/conversation/bot_path.py:47-48` — `_settings = get_settings()` is frozen at first import, so the lock-TTL and `_SEMI_AUTO_INACTIVITY` decisions cannot be reached by a test that clears the settings cache.",
            "`backend/app/core/db.py:16,19-26` — the engine is created at import, binding DSN, `pool_size`, `max_overflow`, `pool_timeout` and `pool_recycle`.",
        ],
        impact=(
            "Importing `app.core.db` anywhere in a test process opens production pool configuration, "
            "`models/base.py` import order becomes load-bearing, and `bot_path.py`'s settings are "
            "unoverridable — a test-hostility and startup-fragility defect."
        ),
        fix=(
            "In `bot_path.py`, replace the module constant with a per-call `get_settings()` read (or "
            "accept settings in `__init__`). For `core/db.py`, keep the engine module-level — correct "
            "for the app — but move it behind a lazy accessor so tests can import `app.models.base` "
            "without opening a pool."
        ),
    ),
    dict(
        id="ARCH-14",
        column="QA_TESTED",
        title="`app/capabilities/` is a live registry with a dormant, hash-verified extension API",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The registry's live half gates installation activation, but `resolve()`, "
            "`export_pack_contract()`, `ResolvedPack.adapter_descriptors` and "
            "`RecruitmentAdapterDescriptor` are reachable only from one test file, and several "
            "definition fields are hashed but never acted on."
        ),
        evidence=[
            "Live: `backend/app/api/installation_dependencies.py:19` and `backend/app/services/installation/service.py:89` call `get_capability_registry()`; `pack_contract_hash` at `service.py:222,321,542,828,864,958`; `IndustryPackDefinition.runtime_ready` at `service.py:961`.",
            "`backend/app/capabilities/registry.py:72` — `resolve()`, ~40 lines of kernel-ABI / schema-version / hash-verification logic; `:104` — `export_pack_contract()`; grep across `backend/` returns only `backend/tests/test_capability_registry.py:182,186-192,200,253,260`.",
            "`backend/app/capabilities/contracts.py:48` — `ResolvedPack.adapter_descriptors`, populated at `registry.py:97` and asserted only at `backend/tests/test_capability_registry.py:259`; `backend/app/capabilities/recruitment/adapter.py:6` — reachable only through it.",
            "`backend/app/capabilities/registry.py:126-145` — `workflow_ids`, `terminology_keys` and `compatible_operational_data` are hashed by `_pack_payload` but never read by production logic.",
        ],
        impact=(
            "The registry advertises a versioned, hash-verified extension point that no code path "
            "enters, so a reader must reason about ~40 lines of dormant verification logic to find out "
            "it is inert."
        ),
        fix=(
            "Keep `pack_contract_hash` and `validate_selection` — they gate installation activation "
            "and are load-bearing. Delete `resolve()`/`export_pack_contract()`/`ResolvedPack`/"
            "`adapter_descriptors`/`RecruitmentAdapterDescriptor`, or add the export endpoint that "
            "would use them."
        ),
    ),
    dict(
        id="ARCH-15",
        column="QA_TESTED",
        title="`services/outbox_service.py` (842 LOC) mixes row lifecycle with three provider dispatch branches",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "One module holds the dispatch value objects, the OA token refresh that happens during "
            "dispatch, the row lifecycle, the authority revalidation and three provider branches. The "
            "dispatcher is the only part that talks to providers."
        ),
        evidence=[
            "`backend/app/services/outbox_service.py:46,56,77,106` — `DispatchCandidate`, `DispatchResult`, `outbound_dispatch_stale_after_seconds`, `build_outbox_payload`; `:86` — OA token refresh during dispatch.",
            "`backend/app/services/outbox_service.py:135,186,218,596,606,619,642` — `create_pending_outbox`, `claim_pending_outbox`, `dispatch_outbox`, `dispatch_message_outbox`, `pending_outbox_ids`, `stale_sending_outbox_ids`, `claim_stale_sending_unknown`.",
            "`backend/app/services/outbox_service.py:354,439,578` — `_try_neutral_dispatch`, `_dispatch_facebook`, `_provider_for_outbox_channel`; `:548` — the Messenger send-window policy guard; `:238-305` — authority revalidation.",
        ],
        impact=(
            "The provider-dispatch surface and the row lifecycle share a module and a review surface, "
            "so a lifecycle change (REL-06 touches `claim_pending_outbox`) is reviewed against three "
            "provider branches."
        ),
        fix=(
            "Natural seam: `outbox/repository.py` (`:135-217`, `:596-657`) versus "
            "`outbox/dispatcher.py` (`:218-595`). The dispatcher is the only part that talks to "
            "providers."
        ),
    ),
    dict(
        id="ARCH-16",
        column="QA_TESTED",
        title="`services/installation/service.py` (1055 LOC) interleaves validation, lifecycle, projection and checksums",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Revision CRUD and validation, the authority-locked lifecycle transitions, runtime "
            "resolution and readiness, the admin/runtime projections and the checksum assembly all "
            "live in one module."
        ),
        evidence=[
            "`backend/app/services/installation/service.py:91,290` — `create_revision`, `validate_revision`; `:441,453,477,495` — `activate_revision`, `rollback_revision`, `suspend`, `resume`, with the authority lock at `:444,456,478,496`.",
            "`backend/app/services/installation/service.py:523,565,577,615,797,881` — `resolve_active`, `require_active`, `assert_current`, `runtime_stamp_is_current`, `_validation_is_current`, `_runtime_readiness`.",
            "`backend/app/services/installation/service.py:620,684,926` — `runtime_view`, `admin_view`, `_active_context`; `:219-256` — checksum assembly.",
        ],
        impact=(
            "This module is also the per-turn hot path (PERF-01), so its size and interleaving make the "
            "authority cost harder to reason about and every turn-latency change lands in a 1055-line "
            "file."
        ),
        fix=(
            "Natural seam: `installation/{lifecycle,validation,projection}.py`. "
            "`app/installation/domain/projection.py` already exists, so the projection half has a home; "
            "the lifecycle half is the part with the authority lock (`:444,456,478,496`) and belongs "
            "together."
        ),
        notes="Hot-path coupling: PERF-01 proposes making `resolve_active()` cache-first in this same module.",
    ),
    dict(
        id="ARCH-17",
        column="QA_TESTED",
        title="The enforced architecture rules miss the real import edges",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The layering rules the two architecture tests encode cover only part of the app, so the "
            "edges that actually violate the ports-first intent sit outside the guard and the guard "
            "gives false confidence."
        ),
        evidence=[
            "`backend/app/realtime/socketio.py:25` — `from app.api.auth_dependencies import get_user_from_token`, transport importing the HTTP auth layer; `realtime/` is not a covered source in `_backend_rule`. `backend/app/services/presence.py:22` — `from app.realtime.emitter import emit_event`, which `service_outward` does not forbid (it lists only `app.{graph,workers,api}`).",
            "`backend/app/reporting/infrastructure/conversation_attention.py:32` — imports `app.services.conversation.repository` although only `reporting/application` is a pure prefix; `backend/app/channels/providers/facebook_account.py:27-28` — imports `app.models.channel_account` and `app.services.audit_service`, and `channels/` is entirely uncovered by the rules.",
            "`backend/app/models/conversation.py:26`, `backend/app/models/job.py:13`, `backend/app/models/lead.py:26` and `backend/app/models/knowledge.py:20` — models import enums from contexts above them, inverting the documented `API → Services → Models/Core` direction.",
            "`backend/app/api/integrations.py:792,830,892,922,1025,1050,1173,1261,1284,1310,1339` and `backend/app/api/webhooks.py:160,183,213,265` — the API layer imports channel providers, which `api_outward` does not list.",
            "The three edges the brief expected to find — `services → api`, `models → services`, `graph → concrete services` — are all absent and machine-enforced with a zero-entry allowlist (`backend/tests/test_architecture_boundaries.py:19`, `backend/tests/test_graph_import_guard.py:35`). Verified, not a defect.",
        ],
        impact=(
            "The next boundary violation lands outside the rule set, exactly as these did. The model "
            "inversions are enum-only so the runtime impact is low, but they invert the documented "
            "direction and make the rule set's coverage claim misleading."
        ),
        fix=(
            "Add `app.realtime`, `app.channels` and `app.reporting` to the covered source list in "
            "`_backend_rule` and add `app.channels` to the `api_outward` target list; each new rule "
            "surfaces a small, fixed set of edges, and the first three rows are a one-line import "
            "inversion each — e.g. `presence.py` should publish through "
            "`conversation_messaging.application.ports.ConversationEventsPort`, which already exists at "
            "`conversation_messaging/application/ports.py:39`. Narrow the `factories.py` exemption in "
            "`test_graph_import_guard.py:35` at the same time (see ARCH-09)."
        ),
        notes=(
            "Split from a merged ticket. The named duplication pairs from audit finding F18 are now "
            "ARCH-19; F18's FAQ and grounding items are ARCH-02 and ARCH-05."
        ),
    ),
    dict(
        id="ARCH-19",
        column="QA_TESTED",
        title="The flat services duplicate the bounded contexts in named pairs",
        sev="medium",
        area="architecture",
        labels=["tech-debt"],
        effort="L",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The flat `app/services/` layer and the bounded contexts implement the same concepts "
            "twice, so a fix must be applied in two places and only one copy is exercised in "
            "production."
        ),
        evidence=[
            "`backend/app/services/knowledge/service.py` (705 LOC) versus `backend/app/services/knowledge_base_service.py` (453 LOC) — both query `Project`/`KnowledgeBase`/`KnowledgeDocument` and both are called from the same router, `backend/app/api/knowledge_bases.py:25-26,134-137`, which selects between them on a `project_id is not None` branch.",
            "`backend/app/services/knowledge/text_ingestion.py:32,41,58,63` — two text-stats functions over two near-identical normalizers whose only difference is that `normalize_kb_scalar` strips `\\r` before the shared pipeline.",
            "`backend/app/services/webhook.py::ZaloWebhookService` (entered via `backend/app/composition/conversation_messaging.py:101-114`) versus `backend/app/channels/ingress.py::ChannelIngressService` (via `backend/app/api/webhooks.py:265-268`) — two different dedup/ensure/record orderings for the same \"inbound text\" concept.",
            "The FAQ pair (`backend/app/services/project/faq.py` chunk-based vs `models/provenance.py` `FaqEntry`) and the grounding pair (`graph/grounding.py` vs the `_ground_*` family in `graph/clients.py`) are ticketed separately as ARCH-02 and ARCH-05.",
            "Deliberately **not** duplication: the legacy `KnowledgeDocument`/`KBVersion` write model versus category revisions is guarded by `_require_legacy_mutation_allowed` (`backend/app/services/knowledge/service.py:652`) and is correct in-flight migration work.",
        ],
        impact=(
            "A change to inbound dedup/ensure ordering or to knowledge text normalisation has to be "
            "made twice, and the two copies can silently diverge — the Messenger and Zalo inbound "
            "paths already order their steps differently."
        ),
        fix=(
            "Merge `KnowledgeBaseService` into `services/knowledge/` as `knowledge/base_service.py` "
            "and collapse the two normalizers into one. Converge Messenger onto `ZaloWebhookService`'s "
            "dedup/ensure/record ordering, or vice versa — pick one shared step list rather than two. "
            "Do this only after ARCH-02 decides which FAQ/fact path is canonical."
        ),
        notes="Split from a merged ticket. The import-edge half is ARCH-17. Sequence after ARCH-02.",
    ),
    dict(
        id="ARCH-18",
        column="QA_TESTED",
        title="Import-time registry validation with failure semantics, and dormant `models/case.py` tables to record rather than drop",
        sev="low",
        area="architecture",
        labels=["tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`capabilities/registry.py` runs its dependency-graph and owner validation during import, "
            "so a pack defect becomes an import-order-dependent startup crash rather than a startup "
            "check. Separately, the `case.py` tables have no runtime reader or writer but sit behind a "
            "load-bearing foreign key, so they cannot be dropped casually."
        ),
        evidence=[
            "`backend/app/capabilities/registry.py:196` — `_REGISTRY = CapabilityRegistry(...)` runs `_validate_dependency_graph` (`:148`) and `_validate_owners` (`:172`) at import, so any pack defect raises `ValueError` while importing `app.capabilities`.",
            "`backend/app/graph/prompts.py:11-13` — the persona read at import is documented as intentional fail-fast, so it is deliberate, not debt.",
            "`backend/app/models/__init__.py:1-8` — imports all 23 model modules, so importing `app.models.base` (which `backend/app/core/db.py:11` does) does not itself register the full `Base.metadata`; `backend/app/models/conversation.py:25-26` adds two more edges to the model import graph.",
            "`backend/app/models/case.py` — `Case`, `CaseNote`, `CaseFollowup`, `CaseTagAssignment`; `backend/app/models/case_workflow.py` — `CaseWorkflowTransition`, `CaseTagDefinition`; grep across `backend/` returns only `backend/app/models/__init__.py:32-45,131-136` and docstrings.",
            "`backend/app/services/installation/service.py:118,306,816` and `backend/app/models/installation.py:51-56` — `CaseWorkflowVersion` is validated and FK-targeted, so the surrounding case tables cannot be dropped in a routine cleanup.",
        ],
        impact=(
            "An import-order-dependent startup crash instead of a startup check, and a future reader "
            "who rediscovers the dormant case tables may drop a table that a live FK depends on."
        ),
        fix=(
            "Move the registry validation into an explicit `verify_registry()` called from app startup "
            "(or a single test), keeping `_REGISTRY` construction as pure data. For `models/case.py`, "
            "do not drop the tables in this pass — Alembic is an approval gate per `AGENTS.md` — "
            "instead mark the dormant models with an explicit comment naming them as "
            "unmapped-in-practice and add a single test asserting they have no importer, so the "
            "dormancy is recorded rather than rediscovered."
        ),
        notes="Merged ticket: covers audit findings F19 and F20 (both low).",
    ),
]
