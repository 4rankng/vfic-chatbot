# Testing Strategy

> Testing approach for the ChatBot (VFIC miniCRM) platform.
> See [`../AGENTS.md`](../AGENTS.md) §8 for test commands, [`../standards/definition-of-done.md`](../standards/definition-of-done.md) for the completion gate.

## Testing Pyramid

```
Unit (pure, no infra)         ← Backend: 65 files | Frontend: 10 files (app project, excluding screenshots)
    ↓
Integration (service + repo)  ← Via Protocol fakes (backend)
    ↓
API (route + auth)            ← Via FastAPI TestClient (limited — most tests are pure unit)
    ↓
E2E (Playwright)              ← Config exists, not yet widely adopted
    ↓
Performance (RAG benchmark)   ← test_rag_benchmark.py
```

## Backend Tests

### Setup
- **Framework:** pytest 8.3 + pytest-asyncio 0.24
- **Config:** `backend/pyproject.toml` → `asyncio_mode = "auto"` (all async tests auto-detected)
- **Conftest:** `backend/tests/conftest.py`
  - Auto-use fixture `_isolate_redis` monkeypatches both Redis singletons to a no-op double.
  - **No live DB, no Redis, no external services.** All tests are pure unit.

### Testing Patterns
- **Protocol-backed fakes.** The graph layer depends on Protocol interfaces (`ports.py`: `ConversationPort`, `RetrievalPort`, `LeadContextPort`, `FaqBypassPort`). Tests inject fakes — no real LLM, DB, or Redis.
- **Worker tests** call async functions directly (via `asyncio_mode = "auto"`), not through RQ.
- **No HTTP client tests** for most routes — the API layer is thin (delegates to services), so testing services directly is preferred. A few integration tests exist (`test_integrations_api.py`, `test_webhooks.py`).

### Test Organization (65 files)
| Area | Example files |
|---|---|
| Graph pipeline | `test_graph_router.py`, `test_graph_runner_turn.py`, `test_graph_clients.py`, `test_graph_factories.py`, `test_graph_safety.py`, `test_graph_proactive_*.py`, `test_graph_import_guard.py` |
| Fast lane / FAQ | `test_fast_lane.py`, `test_faq_bypass.py` |
| Knowledge pipeline | `test_knowledge.py`, `test_knowledge_pipeline.py`, `test_knowledge_coercion.py`, `test_knowledge_text_ingestion.py` |
| Retrieval / RAG | `test_rag_benchmark.py`, `test_retrieval_fusion.py`, `test_retrieval_ann_gate.py`, `test_reranker.py`, `test_semantic_cache.py` |
| Lead | `test_lead_extraction.py`, `test_lead_chatops.py` |
| Recommendation | `test_recommendation_scoring.py` |
| Workers | `test_persistence_worker.py`, `test_reconcile_worker.py`, `test_reconcile_repository.py`, `test_worker_async_runner.py`, `test_worker_preload.py`, `test_scheduler_registration.py` |
| Auth / security | `test_security.py`, `test_password_reset_helpers.py`, `test_ratelimit.py` |
| Concurrency | `test_concurrency.py`, `test_llm_semaphore.py`, `test_direct_lease.py`, `test_direct_turns.py`, `test_parallel_tools.py` |
| Zalo | `test_zalo_bot_service.py`, `test_zalo_oa_*.py` (events, health, service, signature, test_connection, token_refresh) |

### Commands (from `backend/`)
```bash
.venv/bin/pytest                                    # All tests
.venv/bin/pytest tests/test_graph_runner_turn.py    # Single file
.venv/bin/pytest -k "test_fast_lane"                # By keyword
.venv/bin/pytest --tb=short                         # Short tracebacks
.venv/bin/pytest -x                                 # Stop on first failure
```

## Frontend Tests

### Setup
- **Framework:** Vitest 4 + Playwright browser mode
- **Config:** `frontend/vitest.config.ts` — two projects:
  - **`app`** project: Headless Chromium environment. React/DOM unit tests. 80% coverage threshold (lines/functions/branches/statements) for `src/components/atomic-crm/**`.
  - **`claude`** project: Node.js environment. Claude Code hook integration tests in `.claude/hooks/test/`.

### Test Organization (app project — 10 files, excluding `__screenshots__/` auto-generated tests)
| Location | Tests |
|---|---|
| `conversations/` | `chatRepository.test.ts`, `chatOpsWorkspace.test.ts`, `useConversationRealtime.test.ts` |
| `knowledge/` | `knowledgePipelineUtils.test.ts` |
| `layout/` | `workspace-navigation.test.ts` |
| `providers/commons/` | `i18nProvider.test.ts` |
| `providers/rest/` | `api.test.ts`, `api.refresh.test.ts`, `dataProvider.test.ts` |
| `lib/` | `vietnameseSearch.test.ts` |

### Commands (from `frontend/`)
```bash
npm run test:unit:app           # App project (Playwright browser mode)
npm run test:unit:claude        # Claude project (Node mode)
npm run test:unit:app -- --ui   # Vitest UI
```

### E2E
- Playwright config exists at `frontend/playwright.config.ts`.
- E2E build mode: `npm run build:e2e` (vite build --mode e2e).
- Install browsers: `make install-playwright-browsers` (from `frontend/`).

## Mock vs. Real Dependencies

| Layer | Strategy |
|---|---|
| Backend DB | No live DB. Tests use fakes/mocks. Protocol interfaces enable this. |
| Backend Redis | Auto-use `_isolate_redis` fixture replaces Redis with no-op double. |
| Backend LLM | No real LLM calls. `graph/clients.py` is mocked or faked. |
| Frontend API | Custom mocks for dataProvider / authProvider. `testI18nProvider` available. |
| Frontend realtime | Socket.IO mocked in `useConversationRealtime.test.ts`. |

## Regression Policy

- **Never delete a test to make it pass.** If a test fails, fix the code or update the test with a documented reason.
- **Run the full suite before declaring done** (`.venv/bin/pytest` + `npm run test:unit:app`).
- **If you touch a shared contract** (Pydantic schema, Protocol interface, API response shape), run tests in all modules that import it — not just the module you changed.
- **Coverage threshold:** Frontend app project requires 80% lines/functions/branches/statements on `src/components/atomic-crm/**` (excluding `types.ts`).
