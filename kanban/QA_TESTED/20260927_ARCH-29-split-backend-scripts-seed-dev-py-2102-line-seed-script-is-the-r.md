---
id: ARCH-29
title: "Split backend/scripts/seed_dev.py: 2102-line seed script is the repo's #2 churn-weighted deficit"
severity: medium
area: architecture
labels: [god-module, dev-tooling]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-27
---

# ARCH-29 — Split backend/scripts/seed_dev.py: 2102-line seed script is the repo's #2 churn-weighted deficit

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** god-module, dev-tooling

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The repowise production-scope health dashboard ranks seed_dev.py second only to graph/runner.py in weighted health deficit (8,886 points, 3.5% of the repo's total gap to the score-8 target, file score 3.41/10). The whole dev fixture factory lives in one 2102-line script: 23 top-level make_* functions spanning users, projects, companies, personas, jobs, worker features, leads, conversations, messages/bot runs, performance metrics, knowledge, and audit events, plus truncation and the seed() entrypoint. Two functions are brain-methods in their own right: make_messages_and_bot_runs spans roughly 550 lines (:1060-1613) and seed_performance_metrics (:1613) reaches CCN 41 at 4 levels of nesting.

## Evidence

- backend/scripts/seed_dev.py — 2102 lines, 23 top-level functions, file score 3.41/10, weighted deficit 8,886 (repowise get_health production scope, #2 behind runner.py)
- backend/scripts/seed_dev.py:1060-1613 — make_messages_and_bot_runs: ~550-line function building the conversation/bot-run message corpus
- backend/scripts/seed_dev.py:1613-1735 — seed_performance_metrics: CCN 41, nesting depth 4 (repowise nested_complexity biomarker)
- backend/scripts/seed_dev.py:1955 — seed() entrypoint orchestrates all fixture domains inline

## Impact

Any fixture change edits a file every lane has to read; the script has no test file of its own, so seed regressions surface only when a dev environment refuses to boot. Its deficit rank means it is one of the 20 files holding half the repo's health gap.

## Suggested fix

Split into a backend/scripts/seed/ package along the existing make_* seams (one module per fixture domain, shared helpers in a common module), keeping scripts/seed_dev.py as a thin entrypoint that imports seed(). No behavior change: the same fixtures, same IDs, same output — verify by diffing a seeded database before/after.

## Notes

Dev tooling, not the production hot path — priority comes from churn-weighted deficit, not runtime risk.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
