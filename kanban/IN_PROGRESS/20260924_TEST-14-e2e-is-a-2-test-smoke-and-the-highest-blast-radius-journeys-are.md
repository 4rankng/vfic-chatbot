---
id: TEST-14
title: "E2E is a 2-test smoke and the highest-blast-radius journeys are mock-only"
severity: medium
area: testing
labels: [testing]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# TEST-14 — E2E is a 2-test smoke and the highest-blast-radius journeys are mock-only

**Severity:** medium · **Area:** testing · **Effort:** M · **Labels:** testing

**Trạng thái:** TODO

## Problem

The browser suite is exactly two tests — login plus dashboard render, and conversation takeover/release. Nothing exercises knowledge upload through ingestion to a terminal status, persona/adapter assignment, or the bot-run decision-trace UI against the real backend, even though the harness already blocks external network, resets the DB per test and can drive those journeys.

## Evidence

- `frontend/e2e/vfic.spec.ts:3-55` — exactly two tests: login and dashboard render, and conversation takeover/release.
- `frontend/e2e/fixtures.ts:74-97` — external network is blocked and asserted empty at `:88-95`, and the DB is reset per test at `:44-53`, so the harness is already capable of driving real journeys.
- `frontend/playwright.config.ts:37` sets `retries: process.env.CI ? 2 : 0`, so a flaky added spec would burn three times its duration in the closest-to-limit job.
- Backend fixtures for both missing journeys already exist: `e2e_harness.py` seeds, and `backend/tests/integration/test_bot_run_decision_trace_migration.py` covers the trace data shape.

## Impact

The journeys with the largest user-visible blast radius ("I uploaded a document and nothing happened", "the trace panel shows nothing") are covered only by mocked unit tests, so a frontend↔backend integration break passes.

## Suggested fix

Add two e2e specs: upload a knowledge document and assert it reaches a terminal status in the list, and open a conversation's bot-run trace and assert a run row plus its decision-trace detail renders. Both have backend fixtures already.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
