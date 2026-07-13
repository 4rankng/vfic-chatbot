# Chatbot Latency Improvement Plan

- **Created:** 2026-07-12
- **Reviewed:** 2026-07-13
- **Status:** Reviewed; awaiting approval for the Phase 0 production rollout.
- **Goal:** Reduce candidate-visible webhook-to-send latency without weakening grounding,
  ownership checks, delivery guarantees, or answer correctness.
- **Production constraint:** 2 vCPU DigitalOcean droplet.
- **Channel constraint:** Zalo receives complete messages; token streaming is not a usable
  candidate-facing optimization.

## Executive decision

Do not implement the original five phases as written. Most of the proposed machinery
already exists, and two assumptions were unsafe:

- Parallel tool calls, deterministic greetings/thanks/help, FAQ bypass, RAG caches,
  process-wide LLM client reuse, model routing, and latency telemetry are already present.
- A global semantic question-to-answer cache would be unsafe for profile-, history-,
  project-, and job-dependent replies. `"tìm việc làm"` is a personalized recommendation
  intent and must never reuse another candidate's final answer.

The highest-confidence next step is to deploy and measure the optimizations already in
`plans/20260710-chatbot-performance/`, then increase correct zero-LLM coverage and reduce
model round trips for the remaining agent traffic. Provider prompt caching and additional
context-fetch concurrency are conditional follow-ups, not assumed wins.

## Verified current state

| Draft claim | Verified repository state | Planning consequence |
|---|---|---|
| Context retrieval happens in `build_deps()` and is sequential | `build_deps()` wires dependencies. History is read in `runner.py`; system prompt and lead context are assembled in `_agent_turn()`; knowledge retrieval happens through agent tools. | Do not add an `asyncio.gather()` to `build_deps()` for work that is not there. |
| Independent reads can share one `AsyncSession` | SQLAlchemy `AsyncSession` cannot execute concurrent operations. Existing parallel tools correctly open isolated sessions through `session_factory`. | Parallelize only measured read-only work and give each task its own session. |
| Tool calls are sequential | `MiniMaxAgent.agent()` already gathers multiple tool calls concurrently, bounded by `parallel_tool_max_concurrency`. | Validate production utilization; do not rebuild it. |
| No semantic cache exists | `graph/semantic_cache.py` exists and is used only inside unscoped `search_knowledge()`. It caches RAG results, not final replies, and is disabled by default. | Treat it as an optional retrieval optimization with a correctness/invalidation gate. |
| Greetings and common phrases need a new matcher | `graph/fast_lane.py` already handles greeting, thanks, goodbye, help, and meta variants before any LLM call. | Expand only from observed misses; never hard-code factual answers. |
| FAQ bypass is exact-only | FAQ bypass already combines normalized exact matching, vector retrieval, trigram retrieval, score floor, margin, rule terms, and abstention. | Improve KB coverage and tune from production outcomes before changing thresholds. |
| Prompt caching may be unsupported | MiniMax documents automatic prefix caching for M2.7/M2.5 at 512+ input tokens. The app already records `cached_tokens`, and its tool/system/user ordering is cache-friendly. | First verify real cache-hit tokens and latency. Code changes may be unnecessary. |
| Current average is about 7s | The pre-rollout 24-hour baseline in the existing performance plan was p50 21.5s and p95 44.4s webhook-to-send. | Use production percentiles by route, not an assumed average. |

## Targets and measurement contract

Average latency is too sensitive to traffic mix. Release decisions use p50/p95 by lane and
route, with at least 30 agent turns in each comparison window and a comparable route mix.

| Traffic class | Primary target | Guardrail |
|---|---|---|
| Fast lane | Internal lane p95 <100ms; webhook-to-send p95 <=1.5s | No factual query is swallowed by a template. |
| FAQ bypass | Bypass p95 <200ms; webhook-to-send p95 <=2s | Zero wrong canonical answers on the approved FAQ golden set. |
| One-call agent route | Webhook-to-send p50 <=10s, p95 <20s | Grounding and missing-data honesty do not regress. |
| Overall candidate traffic | Improve p50 and p95 by >=30% from the post-deployment baseline | No increase in failed/unknown sends, suppress violations, 429s, degradation replies, or unsafe replies. |
| Stretch goal | One-call agent p50 <=5s | Adopt only if a provider/model benchmark passes the same answer-quality gate. |

Required production slices already captured in `BotRun.stage_timings`:

- `end_to_end_ms`, `webhook_to_pickup_ms`, `preamble_ms`, `db_ms`, `send_ms`;
- `lane`, `intent`, `route_strategy`, `model_tier`;
- `llm_queue_ms`, `llm_model_ms`, `llm_calls`, `llm_call_ms`;
- `tool_ms`, `tool_breakdown`, `tool_calls`, `tool_rounds`, `prefetch_ms`;
- `prompt_tokens`, `completion_tokens`, `cached_tokens`;
- FAQ bypass latency, acceptance/abstention metadata, failures, and delivery outcome.

Add instrumentation only where the current data cannot answer a release question. The
known gap is exact/semantic RAG cache hit-rate telemetry; do not introduce a new tracing
platform for this plan.

## Phase 0 — Deploy and establish the real baseline

- **Priority:** P0
- **Effort:** 0.5-1 day plus a human-approved production rollout
- **Expected impact:** Validates already-implemented removal of the old 5-7s cold preamble
  and avoidable second LLM calls on timetable/FAQ-detail routes.

### Work

1. Deploy the already-implemented `SimpleWorker` preload/warm-start, structured route
   prefetch, parallel tool dispatch, deterministic safety, and end-to-end telemetry.
2. Verify worker startup logs show successful preload and LLM-client warm-up.
3. Capture a post-deployment window with at least 30 agent turns.
4. Compare route-matched before/after percentiles. Separate queue wait, preamble, model
   inference, model-call count, tools, DB, and Zalo send.
5. Record the top five slow route/query shapes. Those observations select Phase 1/2 work;
   do not optimize an unmeasured stage.

### Acceptance criteria

- `webhook_to_pickup_ms + preamble_ms` p95 <2s for queued/recovery turns.
- Successful timetable and FAQ-detail prefetch turns use one LLM call.
- Worker cache warm-up survives multiple turns without rebuilding clients.
- Comparison includes route distribution, sample count, p50/p95, failure rate, 429 rate,
  and fallback/degradation rate.
- No deployment occurs without explicit human approval.

### Related code and evidence

- `backend/app/workers/run_worker.py`
- `backend/app/workers/chatbot_worker.py`
- `backend/app/graph/factories.py`
- `backend/app/graph/clients.py`
- `backend/app/graph/runner.py`
- `backend/app/api/performance.py`
- `plans/20260710-chatbot-performance/`

## Phase 1 — Increase correct zero-LLM coverage

- **Priority:** P1
- **Effort:** 1-2 days after Phase 0
- **Expected impact:** Near-instant replies for additional proven high-frequency traffic;
  hit rate must be measured rather than assumed to be 60-80%.

### Work

1. Build a golden set from production-safe, redacted candidate phrases:
   - non-factual greetings, thanks, farewell, and help/meta variants;
   - canonical factual FAQs and Vietnamese paraphrases;
   - adversarial near-matches that must abstain;
   - personalized queries such as `"tìm việc làm"` that must never use a global reply.
2. Report current fast-lane, FAQ accept, FAQ abstain, and `no_candidates` rates by phrase
   family before changing code or thresholds.
3. Add only observed non-factual misses to `fast_lane.py`. Keep factual salary, shuttle,
   location, requirements, contacts, and active-job answers in the KB-backed lane.
4. Improve canonical FAQ coverage through approved KB content. Tune score floor/margin
   only when the golden set proves better recall with no false accepts.
5. Preserve versioned KB provenance and return canonical answers verbatim on bypass hits.

### Explicit non-goal: generic final-answer semantic cache

Do not cache agent replies globally by message similarity. Final replies can depend on
conversation history, lead profile, project, current job state, and missing-field probing.
The safe fast path is the existing canonical FAQ bypass, whose answer is admin-authored
and whose match can abstain. A future response cache would need an equivalence proof and
keys for every relevant state/version; that duplicates FAQ bypass without a demonstrated
benefit.

### Acceptance criteria

- Zero false fast-lane/FAQ accepts on the golden set.
- All personalized, ambiguous, multi-intent, and cross-project cases abstain to the agent.
- Measured zero-LLM coverage increases from the Phase 0 baseline.
- Fast-lane and FAQ p95 targets are met in production.
- KB updates cannot serve a stale FAQ answer.

### Related files

- `backend/app/graph/fast_lane.py`
- `backend/app/services/retrieval/faq_bypass.py`
- `backend/app/graph/factories.py`
- `backend/tests/test_fast_lane.py`
- `backend/tests/test_faq_bypass.py`
- `backend/tests/test_graph_runner_turn.py`
- project FAQ/KB content managed through the existing versioned ingestion workflow

## Phase 2 — Reduce latency of the agent path

- **Priority:** P1
- **Effort:** 1-2 days, selected from Phase 0 evidence
- **Expected impact:** Fewer LLM round trips and fewer input/output tokens on non-bypass
  traffic. Provider inference remains the long pole.

### Work

1. Rank agent latency by `intent`, `llm_calls`, `llm_model_ms`, `tool_ms`, and
   `completion_tokens`.
2. Extend deterministic prefetch only to a high-volume route where:
   - routing confidence is high;
   - the lookup is read-only and grounded;
   - a prefetch hit allows tool-free, one-call synthesis;
   - miss/error retains the current tool path.
3. Validate existing parallel tool waves in production. Do not parallelize dependent or
   mutating calls. Keep isolated sessions and the concurrency cap.
4. Benchmark retrieval budgets instead of blindly changing `top_k=25` to 3. Compare at
   least 25, 10, 5, and 3 against `benchmark_rag` for evidence recall, grounded answer
   correctness, prompt tokens, and latency. Choose the smallest value that passes quality.
5. Benchmark output caps using representative Vietnamese answers. A shorter reply is
   accepted only if it preserves concrete salary/shift/shuttle/application details and
   one useful next question.
6. Evaluate the already-supported fast model tier on low-complexity grounded routes.
   Previous evidence makes MiniMax M2.5-highspeed a candidate, not an automatic switch.

### Conditional context-fetch concurrency

The system prompt is Redis-cached and lead context is one DB read. Parallelize them only
if their combined p95 is either >300ms or >10% of agent end-to-end latency. If the gate is
met, use independent sessions from `session_factory`; never gather operations on the
turn's shared `AsyncSession`. History read, pending-message write, ownership checks, and
send claims remain ordered because they carry state or delivery invariants.

### Acceptance criteria

- Selected common grounded routes need one LLM call on successful prefetch.
- Per-route p50/p95 improves by >=20% against the Phase 0 post-deployment baseline.
- RAG golden recall and answer groundedness do not regress.
- No increase in tool errors, DB pool exhaustion, 429s, or send failures.
- Prompt/persona, grounding, tool-definition, or model-routing behavior changes receive
  explicit human approval before implementation or rollout.

### Related files

- `backend/app/graph/clients.py`
- `backend/app/graph/router.py`
- `backend/app/graph/tools.py`
- `backend/app/graph/context.py`
- `backend/app/graph/prompt_context.py`
- `backend/scripts/benchmark_rag.py`
- `backend/scripts/benchmark_models.py`
- `backend/tests/test_parallel_tools.py`
- `backend/tests/test_router_tool_gating.py`
- `backend/tests/test_model_tiering.py`
- `backend/tests/test_metrics_capture.py`

## Phase 3 — Validate cache behavior; optimize only on evidence

- **Priority:** P2
- **Effort:** 0.5-1.5 days
- **Expected impact:** Unknown until cache-hit tokens and retrieval-cache hit rates are
  measured. No fixed 1-2s claim is justified yet.

### MiniMax prompt caching

MiniMax M2.7/M2.5 automatic prompt caching already applies to OpenAI-compatible calls
with at least 512 input tokens and uses prefix order `tools -> system -> user`. The current
request is structurally compatible: routed tool schemas and the system prompt precede the
dynamic user/history/profile content.

1. Confirm production responses populate `cached_tokens` for the active model/provider.
2. Benchmark cold vs warm repeated prefixes with the same tool set and system prompt.
3. Track cached-input ratio alongside model latency; compare at least 30 warm calls.
4. If hit rate is low, find prefix churn (tool set, active persona/project index, or message
   ordering) before changing API parameters.
5. Do not add Anthropic `cache_control` to MiniMax's OpenAI-compatible path; MiniMax
   automatic caching requires no request change. OpenRouter behavior must be tested for
   the configured model/provider rather than assumed.

### Existing semantic RAG cache

`semantic_cache.py` avoids some DB retrieval work after an embedding call; it does not
skip final generation. It is off by default and uses a linear Redis scan capped at 200
entries.

1. Add exact/semantic RAG cache hit/miss and lookup-time metrics if Phase 0 shows retrieval
   is a meaningful latency share.
2. Before enabling, test false-positive paraphrases and cross-topic/cross-project cases.
3. Tie semantic entries to the active knowledge version or bump the semantic-cache version
   on every existing `knowledge` cache invalidation. The current standalone bump helper is
   not wired to KB writes, so enabling it unchanged risks stale facts.
4. Enable gradually only if retrieval p95 and hit rate justify the added embedding/scan
   work. Keep personalized memory and recommendations excluded.

### Acceptance criteria

- Prompt-cache status is proven by non-zero provider-reported cached tokens, not inferred.
- Warm prefix latency is statistically compared with cold latency; report p50/p95 and
  sample count.
- Semantic RAG cache has zero false hits on the golden set and invalidates with KB changes.
- Enabling a cache produces a measured end-to-end gain; otherwise leave it disabled.

### Related files

- `backend/app/graph/usage.py`
- `backend/app/graph/clients.py`
- `backend/app/graph/semantic_cache.py`
- `backend/app/graph/tools.py`
- existing KB write paths that call `bump_cache_version("knowledge")`
- `backend/tests/test_usage.py`
- `backend/tests/test_semantic_cache.py`
- `backend/tests/test_graph_tools.py`

## Phase 4 — Rollout, load validation, and closeout

- **Priority:** P1 release gate
- **Effort:** 0.5-1 day per shipped phase

1. Ship one optimization group at a time behind existing configuration where available.
2. Run focused unit tests, then the complete backend suite and Ruff.
3. Run the RAG golden benchmark for any retrieval/context change.
4. Use a production-like load shape on the 2 vCPU target; track DB pool use, event-loop
   health, LLM semaphore wait, queue depth, 429s, and send outcomes.
5. Compare at least 30 agent turns with a route-matched baseline.
6. Roll back the current group if latency fails to improve or any correctness/reliability
   guardrail regresses.
7. Update `standards/performance.md` only after production measurements establish a new
   repeatable baseline.

### Verification commands

From `backend/`:

```bash
.venv/bin/ruff check .
.venv/bin/pytest \
  tests/test_fast_lane.py \
  tests/test_faq_bypass.py \
  tests/test_graph_runner_turn.py \
  tests/test_parallel_tools.py \
  tests/test_router_tool_gating.py \
  tests/test_model_tiering.py \
  tests/test_semantic_cache.py \
  tests/test_usage.py \
  tests/test_metrics_capture.py
.venv/bin/pytest
.venv/bin/python -m scripts.benchmark_rag
```

Provider/model benchmarks make live external calls and require explicit approval and
configured credentials. Deployment also requires explicit approval.

## Prioritization

| Order | Work | Confidence | Why |
|---|---|---|---|
| 1 | Deploy and measure existing worker/prefetch improvements | High | Already implemented against measured 5-7s preamble and two-call route costs. |
| 2 | Improve canonical FAQ coverage and observed non-factual variants | High | Safely skips the LLM when answer provenance is controlled. |
| 3 | Extend one-call grounded routes and tune context/output from benchmarks | Medium-high | Directly attacks model-call count and tokens while preserving a fallback. |
| 4 | Verify automatic prompt caching | Medium | Likely already active; actual gain depends on provider-reported cache hits. |
| 5 | Enable/tune semantic RAG cache | Low-medium | Saves retrieval only, is currently disabled, and needs invalidation/correctness work. |
| 6 | Parallelize more context reads | Low | Current prompt cache + one lead read make the expected gain small; unsafe on a shared session. |

## Explicitly deferred

- Zalo token streaming or partial-message simulation.
- Generic final-answer semantic caching.
- Speculative tool execution, AsyncFC, LLMCompiler, or a graph-framework rewrite.
- A new vector database, Redis Search, external APM, or additional service.
- Model quantization/pruning or self-hosted inference.
- Dependency, database-schema, deployment-topology, prompt/persona, grounding, or tool
  changes without the approvals required by `AGENTS.md`.

## Plan relationship and references

- `plans/20260710-chatbot-performance/` contains the verified production diagnosis and
  already-implemented optimizations. Phase 0 of this document completes its rollout gate.
- `plans/2026-07-12-performance-endpoint-latency/` optimizes the admin dashboard endpoint,
  not candidate reply latency; it is related telemetry work but does not block this plan.
- `docs/research/2026-07-13-llm-agent-latency-optimization.md` is research input only;
  code-backed findings in this plan override generic examples that assume missing features.
- MiniMax prompt caching:
  <https://platform.minimax.io/docs/api-reference/text-prompt-caching>
- OpenRouter prompt caching:
  <https://openrouter.ai/docs/guides/best-practices/prompt-caching>

## Definition of done

- Route-matched production measurements meet the targets above.
- Every shipped phase passes focused tests, full backend tests, Ruff, and relevant RAG
  benchmarks.
- No correctness, grounding, privacy, ownership, delivery, safety, 429, or fallback metric
  regresses.
- Cache invalidation is proven for any enabled cache.
- Final production results and accepted latency budgets are documented from observed data,
  not extrapolated cache-hit assumptions.
