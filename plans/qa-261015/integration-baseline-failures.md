# Pre-existing integration-lane failures (baseline evidence)

**Date:** 2026-10-15
**Purpose:** prove the 9 failing integration tests are pre-existing on clean
`e74355be` (the running prod image), NOT regressions from this branch's fixes.

## Method

1. Full integration lane on the working tree (all fixes applied):
   `cd backend && .venv/bin/python -m pytest tests/integration -q -m integration -p no:randomly`
   → **9 failed, 325 passed** (552.95s).
2. Detached git worktree at clean `e74355be` (no changes), same venv, same dev
   Postgres, narrowed to the three affected files:
   → **9 failed, 81 passed** (251.51s) — identical failure set.

## The 9 (classified)

| Test | Class |
|---|---|
| `test_project_training.py::test_auto_retry_skips_extraction_and_reuses_prepared_categories` | stale test double — monkeypatched `prepare(self, doc, revision, embedder)` lacks the `llm_json` kwarg the product now passes |
| `test_knowledge_version_failure_recovery.py::test_worker_records_configuration_and_database_failures_without_sensitive_errors[provider_configuration]` | stale monkeypatch target — patches `ingestion_module.KnowledgeService`, which the refactored ingestion adapter no longer imports |
| `test_knowledge_version_failure_recovery.py::test_worker_records_configuration_and_database_failures_without_sensitive_errors[database_write]` | same |
| `test_knowledge_version_failure_recovery.py::test_version_ingest_rolls_back_failed_sql_and_keeps_source_for_retry` | stale test double — drives `KnowledgeService.ingest_version`/`KnowledgePipeline` seams the ingestion path no longer uses |
| `test_project_knowledge_export.py::test_export_hides_retired_references_without_rewriting_historical_source[legacy]` | export snapshot/fixture drift — export SQL finds no "in-use knowledge" for the seeded fixture (`ConflictError: Dự án chưa có kiến thức đang sử dụng để xuất.`) |
| `test_project_knowledge_export.py::test_legacy_export_excludes_draft_version_pending_category_and_unlinked_source` | same cluster |
| `test_project_knowledge_export.py::test_legacy_null_reverse_kb_owner_still_exports_declared_project_source[legacy]` | same cluster |
| `test_project_knowledge_export.py::test_export_uses_one_statement_snapshot_and_ignores_cached_authority[category_cutover]` | same cluster |
| `test_project_knowledge_export.py::test_export_uses_one_statement_snapshot_and_ignores_cached_authority[legacy_publication]` | same cluster |

## Scope decision

These live in the **manual** integration lane (owner decision, 2026-09-26,
deployment-guide §1 / K-13) — they are not, and were not, part of the release
gate. Fixing them requires either rewriting ingestion test doubles against the
current adapter surface or deciding export-snapshot semantics — product work
beyond this deploy's approved scope (5 prod findings + deploy). Filed for
follow-up; the changed-surface integration lane added to the release gate in
this change set runs green.

## Not covered

- Whether the export cluster indicates a real export regression visible to
  users (needs product investigation; export endpoint still returns
  ConflictError for projects without published knowledge by design).
- The desktop/mobile Playwright manual lanes (untouched, out of scope).
