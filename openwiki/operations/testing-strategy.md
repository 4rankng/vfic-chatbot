---
type: wiki
title: "Testing pyramid, integration lane, and E2E harness"
description: "Test layers (unit, integration, API, E2E Playwright, RAG benchmark), the disposable PostgreSQL integration lane, and the E2E harness that boots a real stack."
tags: [testing, pytest, vitest, playwright, integration, e2e, rag-benchmark, ci]
sources:
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-bb422ce0a3a7a11a9c5d8af6
    resource: repo://backend/scripts/benchmark_rag.py
  - id: openwiki-source-539ff1e55b1e385204a4bb93
    resource: repo://backend/tests/conftest.py
  - id: openwiki-source-cfb49966522fb2c64a381c26
    resource: repo://backend/tests/e2e_harness.py
  - id: openwiki-source-bf27fb010957bd7d3b81f9b1
    resource: repo://docs/testing.md
  - id: openwiki-source-2090dca405aa9c3acd6c7ff8
    resource: repo://frontend/playwright.config.ts
  - id: openwiki-source-f6ccde2440cc497427ba6702
    resource: repo://frontend/vitest.config.ts
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

# Testing pyramid, integration lane, and E2E harness

TingHire's testing strategy is a five-layer pyramid: unit (pure, no infra) →
integration (real PostgreSQL) → API (route + auth) → E2E (Playwright with a
full stack) → performance (RAG golden-set benchmark). Each layer has a
distinct purpose and infrastructure requirement.

## Backend tests

### Framework and configuration

- **Framework**: pytest 8.3 + pytest-asyncio 0.24
- **Config**: `backend/pyproject.toml` → `asyncio_mode = "auto"` (all async tests auto-detected)
- **Conftest**: `backend/tests/conftest.py`

The default unit lane uses no live DB, Redis, or external services. Two
auto-use fixtures isolate every test:

1. `_isolate_redis` — monkeypatches both Redis singletons (`get_redis`,
   `get_redis` in `app.core.cache`) to a `_NoopRedis` double that always
   reports a miss and discards writes.
2. `_reset_http_singleton_registry` — clears the `httpx` singleton registry
   (`app.core.http._CLIENTS`) before and after each test so no fake or real
   client leaks across tests.

### Protocol-backed fakes

The graph layer depends on Protocol interfaces (`ports.py`:
`ConversationPort`, `RetrievalPort`, `LeadContextPort`, `FaqBypassPort`).
Tests inject fakes — no real LLM, DB, or Redis. Worker tests call async
functions directly (via `asyncio_mode = "auto"`), not through RQ.

### Selected integration lane

`backend/tests/integration/` uses a real local PostgreSQL 16 + pgvector
database and is marked `integration`. The fixture:

1. Creates a unique `vfic_integration_*` database
2. Migrates it to Alembic head
3. Rebinds FastAPI's real database dependency
4. Supplies a rollback-scoped async session
5. Drops the database after the session

Missing PostgreSQL/pgvector fails setup with an actionable error — the tests
never silently skip.

**PostgreSQL safety contract**:
- Async and sync database URLs must identify the exact same endpoint, and the
  host must be loopback-only (`127.0.0.1`, `localhost`, or `::1`)
- Both raw sockets and HTTP requests to non-loopback hosts are rejected
- A database migrated to the current head is expected to contain no business
  rows except 17 legacy `worker_feature_catalog` rows seeded by the
  historical migration chain (a migration oracle, not a clean-install default)

### Commands (from `backend/`)

```bash
.venv/bin/pytest -m "not integration"              # Unit suite, no infrastructure
.venv/bin/pytest -m integration tests/integration/test_harness_smoke.py  # Required PostgreSQL lane
.venv/bin/pytest                                    # Full suite; requires local PostgreSQL
.venv/bin/pytest tests/test_graph_runner_turn.py    # Single file
.venv/bin/pytest -k "test_fast_lane"                # By keyword
.venv/bin/pytest --tb=short                         # Short tracebacks
.venv/bin/pytest -x                                 # Stop on first failure
```

Start the local database before the selected integration lane:

```bash
docker compose -f docker-compose.dev.yml up -d postgres
```

### Test organization

| Area | Example files |
|---|---|
| Graph pipeline | `test_graph_router.py`, `test_graph_runner_turn.py`, `test_graph_clients.py`, `test_graph_safety.py` |
| Fast lane / FAQ | `test_fast_lane.py`, `test_faq_bypass.py` |
| Knowledge pipeline | `test_knowledge.py`, `test_knowledge_pipeline.py` |
| Retrieval / RAG | `test_rag_benchmark.py`, `test_retrieval_fusion.py`, `test_retrieval_ann_gate.py` |
| Lead | `test_lead_extraction.py`, `test_lead_chatops.py` |
| Workers | `test_persistence_worker.py`, `test_reconcile_worker.py`, `test_scheduler_registration.py` |
| Auth / security | `test_security.py`, `test_ratelimit.py` |
| Concurrency | `test_concurrency.py`, `test_llm_semaphore.py`, `test_direct_turns.py`, `test_parallel_tools.py` |
| Zalo | `test_zalo_bot_service.py`, `test_zalo_oa_*.py` |

## Frontend tests

### Framework and configuration

- **Framework**: Vitest 4 + Playwright browser mode
- **Config**: `frontend/vitest.config.ts` — two projects:
  - **`app`** project: Headless Chromium environment. React/DOM unit tests.
    The enforced 80% coverage threshold applies only to the changed/high-risk
    surface: `kernel/index.tsx`, `CredentialSecretField.tsx`,
    `PerformanceTrendChart.tsx`. The full suite currently contains 551 tests.
  - **`claude`** project: Node.js environment. Claude Code hook integration
    tests in `.claude/hooks/test/`.

### Commands (from `frontend/`)

```bash
npm run test:unit:app           # App project (Playwright browser mode)
npm run test:unit:claude        # Claude project (Node mode)
npm run test:unit:app -- --ui   # Vitest UI
```

## E2E (Playwright)

Playwright config lives at `frontend/playwright.config.ts` and starts both a
Vite server and the test-only FastAPI controller in
`backend/tests/e2e_harness.py`.

**Infrastructure per run**:
- Run-specific loopback database ending in `_e2e`
- Local Redis database 15
- E2E-only JWT secret and admin account
- Tests log in through the real FastAPI auth endpoint

**Safety guarantees**:
- Database resets and teardown require ownership markers
- The controller refuses remote or mismatched database URLs, non-`_e2e`
  names, shared Redis databases, non-empty unowned Redis state, and
  destructive actions against an unowned database
- Provider credentials are scrubbed from the FastAPI process
- A process-wide socket guard blocks backend egress
- The Playwright fixture blocks browser requests outside loopback

```bash
docker compose -f ../backend/docker-compose.dev.yml up -d postgres redis
npx playwright test --project=chromium
npx playwright test --project="Mobile Chrome"
npx playwright test                         # All functional + visual projects
```

## RAG golden-set benchmark

`backend/scripts/benchmark_rag.py` runs the retrieval pipeline against a
golden dataset and measures recall@K, precision@K, and MRR. The release gate
(`scripts/release_gate_check.py`) requires a minimum pass rate before any
image is pushed.

## Mock vs. real dependencies

| Layer | Strategy |
|---|---|
| Backend DB | Unit tests use fakes/mocks. Integration lane uses isolated, migrated local PostgreSQL 16 + pgvector. |
| Backend Redis | Unit/integration tests isolate with a no-op double; Playwright uses owned loopback Redis database 15. |
| Backend LLM | No real LLM calls. `graph/clients.py` is mocked or faked. |
| Frontend API | Unit tests use custom dataProvider/authProvider mocks; Playwright uses the test-only FastAPI server and real JWT login. |
| Frontend realtime | Unit tests mock Socket.IO in `useConversationRealtime.test.ts`. |

## CI quality gates

The GitHub Actions `quality-gates.yml` workflow runs on PRs and pushes to
`main`:

| Job | What it runs |
|---|---|
| `backend-unit` | `ruff check .` and `pytest -m "not integration"` |
| `backend-integration` | `pytest -m integration tests/integration/test_harness_smoke.py` against local PostgreSQL 16 + pgvector and Redis |
| `frontend-quality` | `npm run lint`, `npm run typecheck`, `npm run test:unit:app:coverage -- --run`, `npm run build` |
| `functional-e2e` | Playwright on both `chromium` and `Mobile Chrome` projects |
| `release-gate` | Offline golden-result generation with `scripts/benchmark_rag.py --gold` and evaluation with `scripts/release_gate_check.py` |

## Regression policy

- **Never delete a test to make it pass.** Fix the code or update the test
  with a documented reason.
- **Run the full suite before declaring done** (`pytest` + `npm run test:unit:app`).
- **If you touch a shared contract** (Pydantic schema, Protocol interface,
  API response shape), run tests in all modules that import it.
- **Coverage threshold**: Frontend app project requires 80% on the three-file
  enforced surface — not a whole-frontend threshold.
