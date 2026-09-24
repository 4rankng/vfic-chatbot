---
id: ARCH-01
title: "`app/services/ingestion/` is an 18-module subsystem with no production entry point"
severity: high
area: architecture
labels: [tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# ARCH-01 — `app/services/ingestion/` is an 18-module subsystem with no production entry point

**Severity:** high · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

The whole ingestion/template subsystem is reachable only from tests: no API router exposes it, no worker calls it, and a repo-wide grep for `services.ingestion` inside `backend/app` returns only intra-package imports.

## Evidence

- `backend/app/services/ingestion/fact_repository.py` — imported only by `backend/tests/test_fact_repository.py:3,16`; `backend/app/services/ingestion/projector.py` and `review_service.py` — only `backend/tests/test_projector_and_review.py:7,15`.
- `backend/app/services/ingestion/normalization.py` — only `backend/tests/test_ingestion_normalization.py:5`; `structured_llm_extraction.py` — only `backend/tests/test_structured_llm_extraction.py:6`; `state_machine.py` — only `backend/tests/test_ingestion_state_machine.py:10`.
- `backend/app/services/ingestion/template_service.py:155-159` — `TemplateService.preview` has no caller, and the rest of the template cluster (`template_ingestion`, `template_compiler`, `generic_extraction`, `extraction`, `validation`, `limits`, `source_blocks`) is reachable only through it plus three test files.
- `backend/app/services/ingestion/classification.py` — its one in-app importer, `extraction.py:29`, is itself dead.
- `backend/app/main.py:12-27` — registers 15 routers and none is an ingestion-template router; the only `template` routes in `app/api/` are markdown download endpoints (`knowledge.py:64-79`, `personas.py:140-146`, `projects.py:241-258`).

## Impact

~3.5k LOC of unexercised production code that reviewers and agents must reason about, and it carries the only writers of the structured-fact tables (ARCH-02), which makes the provenance schema look live when it is not. Any bug in it is invisible to production.

## Suggested fix

Delete the package, or — if the template-ingestion feature is planned — park it under `backend/experimental/` outside `app/` so it stops being counted as production surface, and add the missing API router in the same change that revives it. Do not leave it in `app/` with test-only callers.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
