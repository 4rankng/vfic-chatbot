---
id: TEST-02
title: "Knowledge-ingestion tests are marked skip, not integration, so they run nowhere"
severity: critical
area: testing
labels: [testing]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# TEST-02 — Knowledge-ingestion tests are marked skip, not integration, so they run nowhere

**Severity:** critical · **Area:** testing · **Effort:** M · **Labels:** testing

**Trạng thái:** QA_TESTED

## Problem

Three knowledge-ingestion test modules carry an unconditional `pytest.mark.skip` with the reason "moved out of unit suite", which is false — they were not relocated. Because the marker is `skip` and not `integration`, they do not run under `-m integration` either, so the pipeline that produces every RAG answer is untested in production shape.

## Evidence

- `backend/tests/test_product_features.py:22-25` — module-level `pytest.mark.skip(reason="integration test: needs live DB + fixtures (moved out of unit suite)")`, killing all ~10 tests.
- `backend/tests/test_knowledge.py:15-20` — the same pattern, killing all 4 tests.
- `backend/tests/test_knowledge_pipeline.py:35-37` — `_integration_skip = pytest.mark.skip(...)` applied to `test_pipeline_run_writes_rich_chunks`, `test_pipeline_run_marks_flagged_low_confidence`, `test_pipeline_retries_on_malformed_then_succeeds` (`:351`) and `test_pipeline_raises_after_retry_failure` (`:368`).
- `backend/tests/test_knowledge_pipeline.py:351-365` — the malformed-LLM-JSON retry branch asserts `calls["n"] == 2` then `doc.status == APPROVED`, and never executes.
- `backend/tests/test_product_features.py:125-137` — the 16-row `extract_product_features` invariant, and re-run idempotency at `:167-179`, are likewise dead source text.

## Impact

The branch handling an LLM that returns malformed JSON during ingestion, the feature-extraction invariant and ingestion idempotency all exist only as source text, so a regression in the RAG ingestion pipeline ships undetected.

## Suggested fix

Convert these to `pytest.mark.integration` and move them under `backend/tests/integration/` so they inherit the disposable-DB fixtures; the `db_session`/`clean_kb`/`clean_features` fixtures (`test_product_features.py:91-102`) are trivially re-expressible against `integration_session`. TEST-01 then makes them actually run.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
