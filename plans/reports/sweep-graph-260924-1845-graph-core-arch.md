# Graph/core architecture sweep — ARCH-05/09/13/14/17/18

Lane: graph/core architecture (sweep-graph). All six tickets landed as
per-ticket commits on `main`. Baseline failures were re-attributed, not
regressed: the two `test_architecture_boundaries` failures that existed before
this lane started are frontend-layer edges (`frontend/src/components/atomic-crm/projects/application/*.ts`
browser globals and application-layer outward imports) and belong to the
frontend lane; they are unchanged by this work. The `test_runtime_surface_inventory`
pair failed transiently mid-sweep while the services lane's uncommitted
`bot_path`/`send_claim`/`bot_outcome` seam WIP sat in the shared tree; their
landed re-pin preserved this lane's constants and both tests pass now.

## ARCH-05 — clients.py seven responsibilities — commit `14199183`

The WIP decomposition modules from checkpoint `0cc29981` had already been
dropped by `20044d94` as unwired dead duplicates, so this lane recreated them
from that checkpoint as the reference and **wired every caller**. Bodies are
verbatim moves; no behavior change.

- `graph/reasoning_compat.py` — reasoning-field wire compatibility
  (`_reasoning_chat_class` with the OpenRouter `cache_control` prefix marker
  preserved byte-for-byte, `_extract_returned_reasoning`).
- `graph/llm_observability.py` — the three Redis counter keys + latency/429
  recorders. `core/ops_health.py` (not this lane's file) still imports the
  keys from `app.graph.clients`, which re-exports them.
- `graph/prefetch.py` — trigger heuristics, project-arg scoping, and the
  fail-open prefetch wrapper. The dispatcher is injected (`dispatch=`) at every
  call site so the agent loop's single tool binding still resolves through
  `clients._dispatch_tool` — that is what `test_parallel_tools` monkeypatches,
  and the injection keeps those patches meaningful.
- `graph/provider_failover.py` — 429/quota predicates, `_bind_like`,
  `_llm_call_with_retry`.
- `graph/grounding.py` — the active-job authority readers and reply grounding
  moved in (public names: `active_job_safe_reply`, `ground_reply`,
  `negative_job_authority`, `matched_job_authority`, `ground_active_job_reply`),
  so grounding has one owner instead of two accidental ones.
- `clients.py` keeps `MiniMaxAgent`, the embedders, and the chat factories:
  1670 → 1166 LOC. The dead `_VACANCY_LOOKUP_UNAVAILABLE_REPLY` constant
  (zero references repo-wide) was removed.
- PERF-05's cache marker and byte-stable prefix are intact (reasoning-payload
  tests green); PERF work untouched otherwise.
- Broad boundary snapshot re-pinned: `provider_boundary` 122 → 119 (three
  dict-`.get` rows changed home module out of the provider-transport-flagged
  clients.py; call sites unchanged). Narrow fixture unchanged by this lane.
- Test imports retargeted to the new homes (`test_graph_clients`,
  `test_llm_failover`, `test_llm_semaphore` including its patch targets
  `app.graph.provider_failover._record_llm_429` / `.asyncio.sleep`).

Note: mid-sweep, a concurrent lane's tree-wide restore reverted several of this
lane's in-flight tracked-file edits (untracked new modules survived). All edits
were re-applied and committed promptly; the landed commits are complete.

## ARCH-09 — factories.py five jobs — commit `f505061c`

- `graph/adapters.py` — the three port adapters (`_DirectContextAdapter`,
  `_FaqBypassAdapter`, `_RuntimePolicyAdapter`) plus the direct-context catalog
  and routing heuristics.
- `graph/client_cache.py` — `_CachedClients`, the process-wide cache, async
  retirement, `reset_client_cache`, and `build_cached_clients` (the fast/failover
  builders are imported function-level to avoid a factories ↔ client_cache
  cycle and to keep `test_llm_failover`'s monkeypatched provider constructors
  effective).
- `factories.py` keeps the LLM builders, page-scope resolution, `build_deps`,
  and the six shims: 1003 → 403 LOC. It re-exports
  `_build_cached_clients` / `aclose_client_cache` / `reset_client_cache` so
  `main.py`, `workers/chatbot_worker.py`, `workers/async_runner.py`, and the
  warm-start tests keep working unmodified (their patches target the factories
  attribute; `build_deps` resolves the alias at call time, so patching still
  intercepts).
- Guard strengthened instead of widened: `test_graph_import_guard.py` no longer
  skips any module wholesale. Non-composition graph modules are fully checked
  (any nesting depth); the three composition modules
  (`adapters.py`, `client_cache.py`, `factories.py`) are checked for the real
  failure mode — a **module-level** concrete models/services import (function
  level is the design). Self-tests pin both detectors.

## ARCH-13 — lazy engine + import-time settings — commit `f30a654c`

Protected path `core/db.py` edited (ticket-required):
- Lines removed/added wholesale around engine construction: `create_async_engine`
  and the sessionmaker moved behind `get_engine()` / `get_session_factory()`
  with module `__getattr__` providing lazy `engine` / `async_session`
  attributes. Justification: the ticket's fix is exactly "move the engine
  behind a lazy accessor so tests can import `app.models.base` without opening
  a pool", while `from app.core.db import engine` (main.py lifespan) keeps the
  app-boot behavior unchanged.
- `get_db` resolves the factory through the module namespace at call time so
  the integration conftest's engine swap still rebinds the dependency.
- `__all__` narrowed to real module globals (`Base`, `get_db`) — ruff F822 on
  the lazy names.
- New `tests/test_core_db.py`: subprocess probe pinning no-build-on-import,
  single-construction cache sharing, and call-time factory resolution with
  rollback semantics.

Deferred (services lane owns the file): `services/conversation/bot_path.py:47`
`_settings = get_settings()` module snapshot — per-call read or constructor
injection; overlaps their ARCH-12. The other snapshots named in the ticket
(`core/redis.py`, `core/security.py`, `realtime/*`, `main.py`) were left alone:
the ticket's suggested fix does not name them and each has lock-in rationale
documented elsewhere.

## ARCH-14 — dormant capabilities extension API — commit `6e13a16e`

Deleted the dormant, hash-verified extension API: `registry.resolve()`,
`export_pack_contract()`, `ResolvedPack`, `CapabilityAdapter`,
`CapabilityDefinition.adapter_descriptor`, and
`capabilities/recruitment/adapter.py` (`RecruitmentAdapterDescriptor`) —
reachable only from the registry's own tests. Kept and untouched:
`pack_contract_hash`, `validate_selection`, `runtime_ready`, and the full
`_pack_payload` (byte-identical, so every stored revision hash still validates
— the published-contract fixture pin `2a7c602a…` moved to a direct
`pack_contract_hash` assertion, preserving the drift guard).

## ARCH-18 — import-time registry validation + dormant case tables — commit `f7a7fb21`

- `CapabilityRegistry.__init__` now does data-shape work only (uniqueness);
  dependency-graph, selection, and owner validation live in an explicit
  `verify_registry()`, pinned by a dedicated CI test on the shipped packs plus
  a new dependency-cycle case. Importing `app.capabilities` can no longer crash
  on a pack defect in import-order-dependent fashion.
- Dormant case tables recorded, not dropped: new
  `tests/test_dormant_case_models.py` asserts `Case`, `CaseNote`,
  `CaseFollowup`, `CaseTagAssignment`, `CaseTagDefinition`,
  `CaseWorkflowTransition` have no importer outside the models package
  (`CaseWorkflowVersion` is live installation surface and deliberately
  excluded). The ticket's suggested comment in `models/case.py` was NOT added —
  `models/` is outside this lane's file ownership under the hard-boundary rule;
  hand-off below.

## ARCH-17 — boundary rules miss real edges — commit `969f1ef8`

Landed (this lane's side — tests are its files):
- `realtime/`, `channels/`, `reporting/` are now covered sources in
  `_backend_rule`. channels/reporting may not import `app.api`/`app.graph`/
  `app.workers`; realtime bans `app.graph`/`app.workers`. All rules land green
  (zero current edges under those target sets; rule-shape unit tests added).
- The factories exemption narrowing (guard now checks composition modules for
  module-level concrete imports) landed with ARCH-09.

Deferred with precise hand-offs (files outside this lane's ownership):
1. `realtime/socketio.py:25` imports `app.api.auth_dependencies` — one-line
   fix: import `build_access_token_authenticator` from
   `app.identity.infrastructure.authentication` (identical verification; errors
   already map to `ConnectionRefusedError`). After that lands, add `"app.api"`
   to realtime's forbidden set and delete the deferral comment.
2. `services/presence.py:22` → `app.realtime.emitter.emit_event` — should
   publish through `conversation_messaging/application/ports.py`
   `ConversationEventsPort` (exists), then add `app.realtime` to
   `service_outward` targets.
3. API layer importing `app.channels` providers (14 sites: `api/integrations.py`
   ×11, `api/webhooks.py` ×3) — needs the ARCH-07 api/integrations refactor;
   then add `app.channels` to `api_outward`.
4. `channels/providers/facebook_account.py:27-28` imports `app.models.*` —
   persistence belongs behind the resolver port; needs a channels refactor no
   ticket currently owns.
5. Models importing bounded-context enums (`conversation.py`, `job.py`,
   `lead.py`, `knowledge.py`) — enum-only inversions, low runtime impact;
   recorded in the rule comment, no rule until the enums move.

## Post-lane hand-offs (lead relayed from the services lane)

- **Port ownership — commit `a2f10e8f`.** `job_features_for_project` and
  `income_summary_for_active_projects` left `ProjectKnowledgeQueryPort`
  (project_knowledge) and are declared directly on `GraphRetrievalPort`
  beside `match_memories`: they are recruitment agent surface served through
  the retrieval facade's recommendation seam, and no bounded-context read
  port claims reads it does not own. Runtime unchanged (the facade already
  implements both); 87 retrieval/tools/inventory tests green, digest
  unaffected (protocol declarations add no call sites).
- **`RecommendationQueryPort` injection in factories — deliberate keep.**
  Wiring `recommendation=` in `build_deps` today would construct the exact
  default (`RecommendationQueries(db, page_project_ids=...)`) the facade
  already builds internally — redundant indirection with no behavioral
  difference. The seam exists for a future recruitment-context implementation;
  when one lands, the wiring is a one-line change at the composition root.
- **Re-pin rule audit.** All landed module moves are covered by the digest
  passing on current HEAD: `14199183` carried its own re-pin (122→119 plus
  digest, in the same commit); the ARCH-09/13 moves add no boundary-category
  call sites (factories/client_cache/adapters/db are not provider-transport
  files, and protocol edits add none) — verified by the inventory tests
  passing on the final tree, which includes the services lane's `5d4633b3`
  ledger covering both lanes' deltas. Rule adopted going forward: any commit
  moving modules into/out of the reviewed boundary set re-pins the snapshot
  digest in the same commit.

## Verification

- Narrow suites per ticket, then widened graph/core set: all green at each commit.
- `ruff check .` tree-wide: clean.
- Full unit lane final run: **2318 passed, 5 failed, 24 skipped**. All five
  failures are attributed outside this lane's blast radius:
  - 2 × `test_architecture_boundaries` — the pre-existing frontend-layer edges
    (frontend lane, present at this lane's start; this lane's new rules flag
    zero edges).
  - 3 × `test_deployment_makefile` — compose-service assertions reading
    `backend/docker-compose.yml`, which the ops lane is editing uncommitted in
    the shared tree right now (their commits `d6b00f88`… landed mid-sweep).
  - Zero failures in graph/, core/db, capabilities/, or any test this lane touched.
- Inventory tests: passing on the final tree (services lane's landed re-pin
  preserved this lane's 119/`e9d34a6f…` constants).

Status: DONE
Summary: All six graph/core architecture tickets landed as six per-ticket
commits (14199183, f505061c, f30a654c, 6e13a16e, f7a7fb21, 969f1ef8) with
narrow-then-broad verification and tree-wide ruff clean; the full lane's five
failures are all attributed to other lanes' in-flight work (frontend edges at
baseline, ops compose WIP), and ARCH-17's five out-of-ownership edges are
recorded hand-offs, not silent scope cuts.
Concerns: shared-tree races are real — a concurrent lane's restore reverted
in-flight edits once (recovered), and the runtime-surface inventory fixture is
re-pinned by multiple lanes against a moving tree; sequencing those re-pins
(avoid landing a re-pin while another lane's seam WIP is uncommitted) would
remove the transient red windows. `bot_path.py` settings snapshot (ARCH-13
half) awaits the services lane.
