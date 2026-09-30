# Testing Strategy

> Testing approach for the ChatBot (VFIC miniCRM) platform.
> The completion gate (definition of done) lives in
> [`code-standards.md`](code-standards.md) (Gate notes).
>
> **Manual + scripted QA of the dev environment** (visual, functional, perf) is
> covered in [`qa-runbook.md`](../ops/qa-runbook.md). The per-feature manual checklist
> lives in [`frontend/qa/TEST_PLAN.md`](../../../frontend/qa/TEST_PLAN.md).

## Testing Pyramid

```
Unit (pure, no infra)         ← Backend pytest + frontend Vitest app suites
    ↓
Integration (selected lane)   ← PostgreSQL 16 + pgvector, migrated to Alembic head
    ↓
API (route + auth)            ← Via FastAPI TestClient (limited — most tests are pure unit)
    ↓
E2E (Playwright)              ← Test-only FastAPI/PostgreSQL/Redis/JWT harness
    ↓
Performance (RAG benchmark)   ← test_rag_benchmark.py
```

## Backend Tests

### Setup
- **Framework:** pytest 8.3 + pytest-asyncio 0.24
- **Config:** `backend/pyproject.toml` → `asyncio_mode = "auto"` (all async tests auto-detected)
- **Conftest:** `backend/tests/conftest.py`
  - Auto-use fixture `_isolate_redis` monkeypatches both Redis singletons to a no-op double.
  - The default unit lane uses no live DB, Redis, or external services.
- **Selected integration lane:** `backend/tests/integration/`
  - Uses a real local PostgreSQL 16 + pgvector database and is marked `integration`.
  - The fixture creates a unique `vfic_integration_*` database, migrates it to
    Alembic head, rebinds FastAPI's real database dependency, supplies a
    rollback-scoped async session, and drops the database after the session.
  - Selecting this lane is mandatory validation, not an optional best-effort
    check. Missing PostgreSQL/pgvector fails setup with an actionable error;
    the tests never silently skip.

### Testing Patterns
- **Protocol-backed fakes.** The graph layer depends on Protocol interfaces (`ports.py`: `ConversationPort`, `GraphRetrievalPort`, `LeadContextPort`, `FaqBypassPort`, `TurnDecisionsPort`, `RuntimePolicyPort`). Tests inject fakes — no real LLM, DB, or Redis.
- **Worker tests** call async functions directly (via `asyncio_mode = "auto"`), not through RQ.
- **No HTTP client tests** for most routes — the API layer is thin (delegates to services), so testing services directly is preferred. A few integration tests exist (`test_integrations_api.py`, `test_webhooks.py`).

### Test Organization (representative files)
| Area | Example files |
|---|---|
| Graph pipeline | `test_graph_router.py`, `test_graph_runner_turn.py`, `test_graph_clients.py`, `test_graph_factories.py`, `test_graph_think_strip.py`, `test_graph_proactive_*.py`, `test_graph_import_guard.py` |
| Decisions / FAQ | `test_graph_decisions.py`, `test_model_tiering.py`, `test_faq_bypass.py` |
| Knowledge pipeline | `test_knowledge.py`, `test_knowledge_pipeline.py`, `test_knowledge_coercion.py`, `test_knowledge_text_ingestion.py` |
| Retrieval / RAG | `test_rag_benchmark.py`, `test_retrieval_fusion.py`, `test_retrieval_ann_gate.py`, `test_reranker.py`, `test_semantic_cache.py` |
| Lead | `test_lead_extraction.py`, `test_lead_chatops.py` |
| Recommendation | `test_recommendation_scoring.py` |
| Workers | `test_persistence_worker.py`, `test_reconcile_worker.py`, `test_reconcile_repository.py`, `test_worker_async_runner.py`, `test_worker_preload.py`, `test_scheduler_registration.py` |
| Auth / security | `test_security.py`, `test_password_reset_helpers.py`, `test_ratelimit.py` |
| Messenger integration | `test_facebook_oauth.py` |
| Concurrency | `test_concurrency.py`, `test_llm_semaphore.py`, `test_direct_lease.py`, `test_direct_turns.py`, `test_parallel_tools.py` |
| Zalo | `test_zalo_bot_service.py`, `test_zalo_oa_*.py` (events, health, service, signature, test_connection, token_refresh) |

### Commands (from `backend/`)
```bash
.venv/bin/pytest -m "not integration"              # Unit suite, no infrastructure
.venv/bin/pytest -m integration tests/integration/test_harness_smoke.py  # Required PostgreSQL lane
.venv/bin/pytest                                    # Full suite; requires local PostgreSQL
.venv/bin/pytest tests/test_graph_runner_turn.py    # Single file
.venv/bin/pytest --tb=short                         # Short tracebacks
.venv/bin/pytest -x                                 # Stop on first failure
```

Start the local database before the selected integration lane:

```bash
docker compose -f docker-compose.dev.yml up -d postgres
```

### PostgreSQL Integration Safety Contract

- Async and sync database URLs must identify the exact same endpoint, and the
  host must be loopback-only (`127.0.0.1`, `localhost`, or `::1`).
- The fixture owns only uniquely prefixed integration databases. It verifies
  migration state, pgvector availability, transaction rollback, and FastAPI
  dependency rebinding against that disposable database.
- Both raw sockets and HTTP requests to non-loopback hosts are rejected for
  the selected lane, so tests cannot reach Zalo, LLM providers, or other
  external services.
- A database migrated to the current head is expected to contain no business
  rows except **17 legacy `worker_feature_catalog` rows** seeded by the
  historical migration chain. That count is a migration oracle, not an
  approved clean-install default or evidence that the runtime is universal.

## Frontend Tests

### Setup
- **Framework:** Vitest 4 + Playwright browser mode
- **Config:** `frontend/vitest.config.ts` — one **`app`** project: headless Chromium environment, React/DOM unit tests.
- **Coverage:** measured over the whole `src/components/atomic-crm` tree under ratchet floors (67 statements / 55 branches / 57 functions / 68 lines — never lowered; raise them as coverage grows), plus 80% per-file gates on the three changed/high-risk files named in the `vitest.config.ts` coverage block.

### Test Organization (representative app-project files)
| Location | Tests |
|---|---|
| `conversations/` | `chatRepository.test.ts`, `chatOpsWorkspace.test.ts`, `useConversationRealtime.test.ts` |
| `integrations/` | `FacebookMessengerIntegrationPage.test.tsx`, `ZaloIntegrationPage.navigation.test.tsx` |
| `knowledge/` | `knowledgePipelineUtils.test.ts` |
| `layout/` | `workspace-navigation.test.ts` |
| `providers/commons/` | `i18nProvider.test.ts` |
| `providers/rest/` | `api.test.ts`, `api.refresh.test.ts`, `dataProvider.test.ts` |
| `lib/` | `vietnameseSearch.test.ts` |

### Commands (from `frontend/`)
```bash
npm run test:unit:app           # App project (Playwright browser mode)
npm run test:unit:app -- --ui   # Vitest UI
```

### E2E
- Playwright config lives at `frontend/playwright.config.ts` and starts both a
  Vite server and the test-only FastAPI controller in
  `backend/tests/e2e_harness.py`.
- Each run uses a run-specific loopback database ending in `_e2e`, local Redis
  database 15, an E2E-only JWT secret, and an E2E-only admin account. Tests log
  in through the real FastAPI auth endpoint.
- Database resets and teardown require ownership markers. The controller
  refuses remote or mismatched database URLs, non-`_e2e` names, shared Redis
  databases, non-empty unowned Redis state, and destructive actions against
  an unowned database.
- Provider credentials are scrubbed from the FastAPI process. A process-wide
  socket guard blocks backend egress, and the Playwright fixture blocks
  browser requests outside loopback.
- The harness replaces retired Supabase provisioning. It is not imported by
  production code and exposes no reset endpoint in the application.
- E2E build mode: `npm run build:e2e` (`vite build --mode e2e`).
- Install browsers: `make install-playwright-browsers` (from `frontend/`).

Start local PostgreSQL and Redis, then run Playwright:

```bash
docker compose -f ../backend/docker-compose.dev.yml up -d postgres redis
npx playwright test --project=chromium
npx playwright test --project="Mobile Chrome"
npx playwright test                         # All functional + visual projects
```

The visual projects render zero-backend pages only: `VFIC_VISUAL_ONLY=1 npx playwright test --project=visual-desktop --project=visual-mobile` needs just the Vite server, and the committed `-linux` baselines are generated and verified inside `mcr.microsoft.com/playwright:v1.60.0-noble` — regenerate them in that same image after any intentional login-shell change.

The controller prepares and resets its owned stores automatically and drops
the E2E database during global teardown.

## Mock vs. Real Dependencies

| Layer | Strategy |
|---|---|
| Backend DB | Unit tests use fakes/mocks. The selected integration lane uses an isolated, migrated local PostgreSQL 16 + pgvector database. |
| Backend Redis | Unit/integration tests isolate Redis with a no-op double; Playwright uses owned loopback Redis database 15. |
| Backend LLM | No real LLM calls. `graph/clients.py` is mocked or faked. |
| Frontend API | Unit tests use custom dataProvider/authProvider mocks; Playwright uses the test-only FastAPI server and real JWT login. |
| Frontend realtime | Unit tests mock Socket.IO in `useConversationRealtime.test.ts`. |

## Root Quality Gates

There is no CI. `make release-check` (repo root) is the whole gate set, and it must pass before any image is built or production is touched. `make deploy` does not run it — run `make release-check` before deploying (the `deploy-backend` / `deploy-frontend` fast-tracks still run it as a prerequisite). Lanes:

| Lane | What it runs |
|---|---|
| backend unit | `ruff check .` and `pytest -m "not integration"` in `backend/`. |
| frontend quality | `npm run lint`, `npm run typecheck`, `npm run registry:check`, the app unit suite, the changed-surface coverage gate, and `npm run build` in `frontend/`. |
| release gate | Offline golden-result generation with `scripts/benchmark_rag.py --gold` and evaluation with `scripts/release_gate_check.py`, which the gate runs with `RELEASE_GATE_LATENCY_SLO_ENABLED=false` — the latency SLO needs production telemetry a dev machine never has, so it reports `not evaluated` and the golden pass rate is the enforced check. |

The backend integration suite (`pytest -m integration`) and functional Playwright
E2E remain available as **manual lanes** (see above for their startup commands)
but are no longer part of the pre-deploy gate: since 2026-09-26 the gate runs
unit-only so a deploy never depends on local dev infrastructure (local
PostgreSQL/Redis ports being free, no local web server).

`make deploy` additionally runs the blue/green smoke turn (`scripts/smoke_turn.py`) against the live new colour before the Caddy flip, and `scripts/turn_pipeline_check.py` after it.

## Regression Policy

- **Never delete a test to make it pass.** If a test fails, fix the code or update the test with a documented reason.
- **Run the full suite before declaring done** (`.venv/bin/pytest` + `npm run test:unit:app`).
  The backend full suite includes the required PostgreSQL integration lane, so
  local PostgreSQL + pgvector must be available.
- **If you touch a shared contract** (Pydantic schema, Protocol interface, API response shape), run tests in all modules that import it — not just the module you changed.
- Messenger OAuth lifecycle changes are covered by `backend/tests/test_facebook_oauth.py` plus the frontend unit tests in `frontend/src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.test.tsx` and `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.navigation.test.tsx`. Keep the backend and frontend assertions aligned when touching that flow.
- **Coverage threshold:** Frontend coverage is ratcheted over the whole `src/components/atomic-crm` tree (floors 67 statements / 55 branches / 57 functions / 68 lines — never lowered) plus 80% per-file gates on the three changed/high-risk files named in `vitest.config.ts`. Backend coverage is report-only: pytest-cov is a dev dependency, but no threshold is enforced.

## Phase 1 Characterization Boundary

The Phase 1 baseline adds explicit empty/recruitment/product-advisory fixtures,
runtime-surface and fallback inventories, migration-oracle tests, the selected
PostgreSQL lane, and the Playwright harness described above. These artifacts
freeze current recruitment behavior for later refactoring; they do **not**
change production code or runtime semantics, activate another industry, or
establish that the platform is universal.

The completed DDD migration enforces a zero-exception dependency matrix in
`tests/test_architecture_boundaries.py`, the hashed route/queue/outbox/provider
surface in `tests/test_runtime_surface_inventory.py`, and graph-to-service
direction in `tests/test_graph_import_guard.py`. The runtime inventory scans the
complete backend application tree, including bounded-context adapters and
composition roots. Updating any snapshot requires an explicit architecture
review.
