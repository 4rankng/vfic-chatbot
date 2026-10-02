# KB evidence grounding — completion record

- Task: Fix two reported defects — (1) a project's "Thông tin tư vấn" counter stuck
  at 4/12 while the category panel reported 12/12 categories with data, and
  (2) uploading `4p-electronics.md` to a project's knowledge base failed with
  "Lỗi nạp".
- Scope: the two evidence-grounding gates in the knowledge service
  (`_coerce_feature` and the whole-brief category-plan validator) plus their
  contract tests. No API, schema, migration, frontend, or product-surface change.
- Files changed:
  - `backend/app/services/knowledge/coercion.py`
  - `backend/app/services/knowledge/category_plan_grounding.py`
  - `backend/app/services/knowledge/extraction.py`
  - `backend/tests/test_extract_category_plan.py`
  - `backend/tests/test_knowledge_coercion.py`
- Instructions retrieved: `AGENTS.md`, `docs/development/code-standards.md`,
  `standards/review-checklist.md`,
  `standards/agent-completion-checklist.md`, `docs/journals/README.md`.
- Approval required: no (bug fix inside the existing architecture; no protected
  operation — no deploy, commit, migration, or production write).
- Approval evidence: N/A — production was read-only (psql `SELECT` and worker
  `docker logs`).

## Root cause (proved, not inferred)

Both symptoms are the same defect: **evidence verification compared raw strings,
so a genuine quote that did not match the source byte-for-byte was treated as
fabricated.**

1. Upload failure ("Lỗi nạp"). Production: document
   `19d372ba-1c0b-4706-8735-09bc52aab090` (`4p-electronics.md`, FAILED) with
   `CategoryPlanExtractionError`; the ingest worker log ends at
   `extraction.py:255 raise ... "Category record has no matching source quote"`.
   Replaying the provider's own output through the real
   `extract_category_plan` reproduced it locally: 8 categories rejected with
   "Category record contains text absent from its evidence" — e.g. the record's
   `rotation` joined two bulleted source lines, and `notes` restated a line the
   record had not listed in its own quotes. One bad record voided the whole file.
2. Readiness counter (4/12). `_coerce_feature` verified the whole
   `evidence_text` as one folded substring. Running the real
   `KnowledgePipeline.extract_product_features` against the real file with the
   production digest model returned 12 concrete answers and published **0/12**:
   every evidence string either dropped the source's markdown emphasis
   (`- **Kỳ hạn trả lương:** Trả lương theo tháng.`) or joined several source
   lines. Commit `6926f87e` made that degradation silent per candidate, so the
   counter keeps whatever the last successful run left (4/12 in production) and
   would have read 0/12 after the next successful upload.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Both defects fixed and re-verified end to end. Category lane: `extract_category_plan` on the real `4p-electronics.md` with saved provider output writes all 12 categories (was: whole upload failed); a fresh `deepseek/deepseek-v4.1-flash` call writes 11/12 (the model itself returned an empty `transportation` list that run). Feature lane: real `KnowledgePipeline.extract_product_features` with the production digest model now yields `ready=11/12` (twice); only `joining_bonus`, which the model itself reports as `is_missing`, stays empty. |
| Diff is limited to the approved scope | PASS | `git diff --stat` limited to the three knowledge modules plus their two test files; no other path touched. |
| Protected operations were avoided or approved | PASS | No deploy/commit/migration. Production accessed read-only: `docker exec … psql -c "select …"` and `docker logs` only. |
| Focused tests/checks pass | PASS | `.venv/bin/python -m pytest tests/test_extract_category_plan.py tests/test_knowledge_coercion.py -q` → 88 passed; with the five related suites added (`test_auto_training_features`, `test_auto_project_training`, `test_project_training`, `test_ingest_feature_extraction`, `test_training_source_coverage`, `test_brief_fixture_ingestion`, `test_project_catalog_features`, `tests/integration/test_project_training.py`) → 191 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `.venv/bin/python -m pytest tests/ -q -k "knowledge or training or feature or categor or coerc or ingest or grounding"` → 801 passed, 12 failed. All 12 are pre-existing: stashing this change and rerunning the same files gives the identical 12 (`test_knowledge_version_failure_recovery.py` 3, `test_project_knowledge_export.py` 5, `test_knowledge_ingestion.py` 4 — stale legacy-KB-lane tests of commit `2674fc79`). `tests/test_architecture_boundaries.py` → 21 passed. |
| Lint passes for affected code | PASS | `.venv/bin/python -m ruff check app/services/knowledge/ tests/test_extract_category_plan.py tests/test_knowledge_coercion.py` → All checks passed. Repo-wide `ruff check .` → 13 errors, all in files this change does not touch (`app/graph/lanes.py`, `app/schemas/knowledge.py`, two unrelated test files), verified pre-existing. |
| Type checking passes for affected code | PASS | `uvx pyright app/services/knowledge/coercion.py app/services/knowledge/category_plan_grounding.py app/services/knowledge/extraction.py` → 0 errors, 0 warnings. (`make check` scopes pyright to `app/graph`, untouched.) |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.services.knowledge.extraction, app.services.knowledge.category_plan_grounding"` → import ok; the three suites above import and exercise the changed modules. |
| Security and privacy impact reviewed | PASS | The change only removes claims: an unsupported value is CLEARED, never published, and a record left with no facts is rejected. Quotes must still be verbatim source text. Logs carry the category key and the cleared field paths only — no source text, no provider output (`CategoryPlanExtractionError` keeps that contract). |
| Performance and async-I/O impact reviewed | PASS | No new I/O. Added work is pure string tokenisation over text already in memory, once per record/feature; no query, provider call, or loop nesting added. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. New operator-facing failure text is Vietnamese and mapped in `CategoryPlanExtractionError` ("Bản ghi trích xuất chưa khớp với nguồn tệp. Vui lòng kiểm tra tệp rồi thử lại."). |
| Error handling and compatibility reviewed | PASS | Domain error types and their mapped Vietnamese messages are preserved; one new message is added. `extract_category_plan` still raises when nothing verifies (no silent empty import), still returns `None` for a genuinely fact-free source, and the checkpoint-replay path stays deterministic (saved records re-validate). Upload/queue, publish, and readiness contracts are unchanged. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | No routed document describes these gates. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." Durable decision recorded in `docs/journals/261002-evidence-grounding-word-tokens.md`. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added (`grep -n "TODO\|FIXME\|HACK"` over the changed files shows nothing new). |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | Only the five intended files are modified by this task; other dirty paths in the tree are pre-existing user work (`conversation/`, `dashboard/`, frontend automation) and were left untouched. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Production project `4P Electronics` (`e1fcceee-…`) still renders 4/12 until
    the fixed build is deployed and the project ingests successfully again (the
    failed source `19d372ba-…` is reused and requeued on the next upload of the
    same file) or an operator runs the manual feature re-extraction.
  - Value grounding for category fields now checks the whole source section, not
    only the record's cited quotes. The quotes must still be verbatim, but a
    value may rest on a line the record cited elsewhere in the same file; that
    was a deliberate trade to stop dropping whole categories over a subset
    citation.
  - A same-file re-upload of an already COMPLETED training source is treated as
    a no-op retry by `training_source_reusable`; refreshing feature values on an
    unchanged file still needs the manual extraction action.
  - Twelve integration tests in the tree fail at HEAD (legacy KB-version lane
    removed in `2674fc79` without updating them); they are outside this scope
    but will fail any integration run until retired.
