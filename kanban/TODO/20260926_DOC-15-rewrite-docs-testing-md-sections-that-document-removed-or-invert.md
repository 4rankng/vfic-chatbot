---
id: DOC-15
title: "Rewrite docs/testing.md sections that document removed or inverted test infrastructure"
severity: medium
area: docs
labels: [documentation, testing, ci]
effort: M
status: todo
column: TODO
opened: 2026-09-26
---

# DOC-15 — Rewrite docs/testing.md sections that document removed or inverted test infrastructure

**Severity:** medium · **Area:** docs · **Effort:** M · **Labels:** documentation, testing, ci

**Trạng thái:** TODO

## Problem

docs/testing.md still describes the pre-sweep test infrastructure in five places: the deleted claude vitest project and its npm script, the old three-file-only coverage policy (now inverted into a whole-tree ratchet), a CI jobs table that predates the functional-e2e split, a removed test_fast_lane.py, and the old port names.

## Evidence

- docs/testing.md:100-101,:117 — documents a `claude` Vitest project and `npm run test:unit:claude`; vitest.config.ts defines exactly one project and package.json has no such script (removed in 'drop the dead vitest claude project script')
- docs/testing.md:100,:184 — 'The enforced 80% coverage threshold applies only to the changed/high-risk surface'; vitest.config.ts:19-53 now enforces whole-tree ratchet floors 67/55/57/68 over all of atomic-crm plus three 80% per-file gates — the doc denies a threshold that now exists
- docs/testing.md:170-174 — CI table lists backend-unit without the docs-drift/coverage steps, omits functional-e2e entirely, and describes visual-e2e as chromium+Mobile Chrome; quality-gates.yml actually defines six jobs with functional-e2e (matrix chromium/Mobile Chrome) and visual-e2e (visual projects only, zero-backend)
- docs/testing.md:52,:69 — cites test_fast_lane.py and `pytest -k "test_fast_lane"`; no such file exists and test_model_tiering.py:16-17 records 'The template fast lane was removed'
- docs/testing.md:44 — port list includes the nonexistent RetrievalPort (actual exports: graph/ports.py:261-266)

## Impact

testing.md is AGENTS.md's designated testing source of truth. `npm run test:unit:claude` fails with 'missing script'; an agent that trusts :184 may delete non-three-file tests believing nothing else gates coverage, then fail the CI ratchet; the CI table misroutes debugging (a chromium/Mobile Chrome failure lands in visual-e2e per the doc, but that job doesn't run those projects); the fast-lane row sends contributors to a file that no longer exists.

## Suggested fix

One docs/testing.md pass: delete the claude-project bullet and the test:unit:claude command (:100-101,:117); rewrite :100/:184 to the whole-atomic-crm ratchet (67/55/57/68 floors + three 80% gates); rebuild the CI table from quality-gates.yml's six jobs including functional-e2e; replace the Fast-lane row :52 with the current graph lane files (test_graph_decisions.py, test_model_tiering.py) and drop the -k example :69; correct :44 to GraphRetrievalPort. Note backend coverage is report-only (TEST-18) if the coverage section is rewritten.

## Notes

Pure doc drift; cross-ref TEST-18 (the ratchet itself) is a separate fix.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
