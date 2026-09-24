---
id: TEST-05
title: "No contract test links the frontend data provider to the backend routes"
severity: high
area: testing
labels: [testing]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# TEST-05 — No contract test links the frontend data provider to the backend routes

**Severity:** high · **Area:** testing · **Effort:** M · **Labels:** testing

**Trạng thái:** QA_TESTED

## Problem

The frontend data provider asserts hardcoded URL strings with no link to the backend, and the backend pins its route surface only against itself. A route rename, a prefix move or a resource-to-path remap therefore keeps both suites green while the console 404s.

## Evidence

- `frontend/src/components/atomic-crm/providers/rest/dataProvider.test.ts:62` — `expect(url).toContain("/api/v1/leads?")`, a hardcoded string with no link to the backend.
- `frontend/src/components/atomic-crm/providers/rest/dataProvider.test.ts:99` — asserts the `knowledge_sources` → `/api/v1/knowledge/documents?` alias, direct evidence this drift class already happened once and was patched by hand.
- `backend/tests/test_runtime_surface_inventory.py:31-52` — backend route truth is pinned only against itself via per-module route counts and `EXPECTED_ROUTE_INVENTORY_SHA256`, which catches the backend changing but not the frontend failing to follow.
- `backend/tests/test_single_page_external_source_sync_api.py:76-82` — the only openapi assertion reads `main_app.openapi()["paths"]` and checks backend-authored paths.

## Impact

A route rename or prefix move keeps both suites green while the console 404s, and the existing alias test is proof this has already happened once.

## Suggested fix

Add a backend unit-lane contract test (no DB needed) that imports `main_app.openapi()["paths"]` and asserts every `resource → (path, method)` pair the dataProvider emits resolves to a real route, driven from a single shared table so the dataProvider test and the contract test cannot drift.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
