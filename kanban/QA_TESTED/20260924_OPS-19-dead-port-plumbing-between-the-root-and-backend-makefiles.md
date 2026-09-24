---
id: OPS-19
title: "Dead PORT plumbing between the root and backend Makefiles"
severity: medium
area: ops
labels: [ops, documentation]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# OPS-19 — Dead PORT plumbing between the root and backend Makefiles

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, documentation

**Trạng thái:** QA_TESTED

## Problem

The root Makefile documents `make dev PORT=9000` and forwards `PORT` to `backend/Makefile`, which never references it — it defines `BACKEND_PORT`, `FRONTEND_PORT` and `ZALO_MOCK_PORT` instead. The troubleshooting doc repeats the same dead override.

## Evidence

- `Makefile:3-13` — documents "Port shared by backend (uvicorn) and frontend (Vite) … `make dev PORT=9000`" and invokes `$(MAKE) -C backend dev PORT=$(PORT)`.
- `backend/Makefile:3-5` — defines `BACKEND_PORT ?= 8000`, `FRONTEND_PORT ?= 5173`, `ZALO_MOCK_PORT ?= 8788` and never references `PORT`; its own comment at `:63` tells users to `make dev BACKEND_PORT=8001`.
- `docs/troubleshooting/README.md:67` — "Port 5173 (or custom `PORT`) in use?" — an override that does nothing.

## Impact

The documented override silently does not apply: a user with port 5173 busy gets the same failure they were trying to fix, and no diagnostic.

## Suggested fix

Delete `PORT` from `Makefile:3-13` and forward the three real variables (`BACKEND_PORT`, `FRONTEND_PORT`, `ZALO_MOCK_PORT`), or make `backend/Makefile:3-5` honour `PORT` as a fallback for `FRONTEND_PORT`; fix `docs/troubleshooting/README.md:67` to match.

## Notes

Merge with OPS-18 — the same first-run path.

## Evidence log

- 29446018 — root PORT deleted as dead plumbing; dev forwards FRONTEND_PORT (the variable backend reads)
- verified: make -n dev shows FRONTEND_PORT=$(PORT); backend/Makefile never references PORT
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
