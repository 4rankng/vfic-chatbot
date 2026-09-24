---
id: PERF-06
title: "Turn preamble serialises four independent steps"
severity: medium
area: performance
labels: [performance]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# PERF-06 — Turn preamble serialises four independent steps

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance

**Trạng thái:** QA_TESTED

## Problem

`run_turn` runs the pending record, the lead-gender lookup, the Jev HTTP call and project/direct-context resolution strictly in sequence, although only Jev consumes another step's output.

## Evidence

- `backend/app/graph/runner.py:1299` — `record_bot_pending`; `:1338` — lead-gender lookup; `:1346` — `decide_turn`; `:1392` — project/direct-context resolution; then `_resolve_lane`. All sequential; only Jev needs `recent_messages`, fetched at `:1284`.
- `backend/app/graph/decisions.py:34-37` — the Jev call is documented at 70–500 ms with a 3.5 s ceiling; `:335` — it uses its own httpx client and touches no DB.
- The project/direct-context step at `:1392` is the uncached full-KB scan ticketed as PERF-04, making it the most expensive member of the serial chain.

## Impact

~0.5–4 s of avoidable serial latency on every turn before the first LLM token [EST] — on a 10 s SLA that is the difference between a fast answer and the `soft_fallback_remaining` path.

## Suggested fix

`asyncio.gather` the Jev call with `record_bot_pending` (Jev uses its own httpx client and touches no DB) and with the lead-gender lookup only if that lookup is given an isolated session (`worker_session_factory()`, already used at `backend/app/workers/chatbot_worker.py:489`). Keep DB-touching ORM calls sequential because the shared `AsyncSession` is explicitly not concurrency-safe (documented at `factories.py:652-657` and `dashboard/service.py:66`).

## Notes

Split from a merged ticket. The duplicate lead-resolution half is now PERF-14; the expensive member of this chain is ticketed as PERF-04.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
