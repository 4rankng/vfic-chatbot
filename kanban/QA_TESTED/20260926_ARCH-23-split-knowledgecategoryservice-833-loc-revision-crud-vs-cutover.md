---
id: ARCH-23
title: "Split KnowledgeCategoryService (833 LOC): revision CRUD vs cutover/rollback vs unit rendering"
severity: medium
area: architecture
labels: [god-module, knowledge]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-26
---

# ARCH-23 — Split KnowledgeCategoryService (833 LOC): revision CRUD vs cutover/rollback vs unit rendering

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** god-module, knowledge

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

services/knowledge/category_service.py is 833 lines and the service class owns four distinct jobs: category revision staging/activation/clear, category-authority cutover and rollback with snapshot surgery, cross-category job-reference validation, and RAG unit rendering. activate_revision alone spans ~198 lines. The cutover/rollback snapshot logic — the riskiest code, it rewrites project pointers — is buried between CRUD methods.

## Evidence

- backend/app/services/knowledge/category_service.py:65 — KnowledgeCategoryService spans :65-789 in an 833-line file
- backend/app/services/knowledge/category_service.py:306 — activate_revision runs :306-503 (lease, validation, projection rebuild, embed, activate)
- backend/app/services/knowledge/category_service.py:563 — cutover_category_authority (:563-635) and rollback_category_authority (:637-698) manually rewrite category pointers, project projection fields and snapshots
- backend/app/services/knowledge/category_service.py:741 — _validate_active_job_references cross-checks JOBS ids across sibling category revisions (domain rule inside the service)
- backend/app/services/knowledge/category_service.py:791 — module-level _render_units (:791-833) builds embedder input units, a rendering concern unrelated to the transactional service

## Impact

Cutover/rollback is the highest-blast-radius knowledge operation and is unreviewable inside a mixed 833-line module; a regression in rendering or validation ships coupled to authority-pointer rewrites, and tests must construct the whole service to exercise one concern.

## Suggested fix

Extract cutover/rollback (with _require_rag_project/_locked_project/_locked_category helpers and the snapshot dataclass) into knowledge/category_authority.py; move _render_units into category_projections.py or the category definition module it already reads; move _validate_active_job_references next to validate_job_references in category_contracts.py. Keep KnowledgeCategoryService delegating so api/knowledge.py call sites are unchanged.

## Notes

The knowledge package is one of the churn-heaviest areas since the wave-1 audit.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
