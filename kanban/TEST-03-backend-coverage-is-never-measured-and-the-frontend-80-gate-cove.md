---
id: TEST-03
title: "Backend coverage is never measured and the frontend 80% gate covers 3 of 425 files"
severity: critical
area: testing
labels: [testing, ops]
effort: M
status: todo
found: 2026-09-24
---

# TEST-03 — Backend coverage is never measured and the frontend 80% gate covers 3 of 425 files

**Severity:** critical · **Area:** testing · **Effort:** M · **Labels:** testing, ops

## Problem

The backend has no coverage tooling at all: `pytest-cov` is not a dependency and no `--cov` flag appears anywhere in CI or the Makefile. The frontend's 80% gate is real but its `coverage.include` names exactly three paths, so the number reads as a project-wide gate while covering 3 of 425 files.

## Evidence

- `backend/pyproject.toml:60-67` — dev dependencies are `pytest`, `pytest-asyncio` and `ruff`; there is no `pytest-cov`, no `addopts`, and no `--cov` anywhere in CI or `Makefile`.
- `frontend/vitest.config.ts:19-23` — `coverage.include` is exactly `capabilities/kernel/index.tsx`, `integrations/CredentialSecretField.tsx` and `performance/PerformanceTrendChart.tsx`; `:26-31` sets flat 80% thresholds on lines, functions, branches and statements.
- `.github/workflows/quality-gates.yml:143` — runs `npm run test:unit:app:coverage:changed-surface -- --run`, so the 80% figure is presented as a CI gate.

## Impact

A change that guts `backend/app/graph/runner.py` (1,259 lines), `app/services/conversation/bot_path.py` (1,118 lines) or `app/services/outbox_service.py` produces no signal at all. On a 2 vCPU / 4 GB single droplet, untested hot paths are exactly where latency and correctness regressions land.

## Suggested fix

Add `pytest-cov` to the backend dev extra and run `--cov=app --cov-report=term-missing` in the `backend-unit` job — report-only at first, then a ratchet floor. Extend the frontend `include` to `src/components/atomic-crm/**` with a ratchet threshold rather than a flat 80%, keep the 3-file contract as an additional strict sub-gate, and relabel the CI step so it does not read as whole-tree coverage.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
