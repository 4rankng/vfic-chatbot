---
id: TEST-17
title: "Retire the TEST-10 raw-source assertion tail: it grew from ~30 pins in 7 files to ~135 in 14"
severity: medium
area: testing
labels: [raw-source-assertions, frontend, test-debt]
effort: L
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-17 — Retire the TEST-10 raw-source assertion tail: it grew from ~30 pins in 7 files to ~135 in 14

**Severity:** medium · **Area:** testing · **Effort:** L · **Labels:** raw-source-assertions, frontend, test-debt

**Trạng thái:** TODO

## Problem

TEST-10's deferred tail was ~30 raw-source assertions in 7 files. Recounting at HEAD: 9 frontend test files import ~30 production files via `?raw` and make ~120 expect-sites against that text (CSS selector/property regexes plus literal TSX source strings), and 5 backend test files make ~13 more string-level assertions against app/migration/script/test sources — ≈135 sites across 14 files, >4x the baseline. Wave 1 already proved the better pattern twice (mobile-workspace and the inbox layout tests render real components and assert computed styles), but the bulk of the class was added/kept while colocating feature tests.

## Evidence

- frontend/src/components/atomic-crm/integrations/settings.css.test.ts:3-14,83-104 — imports 4 TSX sources + 2 stylesheets ?raw; ~24 toMatch/toContain sites incl. literal JSX strings in ZaloIntegrationPage.tsx
- frontend/src/components/atomic-crm/users/account-layout-regressions.test.ts:42-52 — asserts zod schema calls inside UserCreate.tsx/UserEdit.tsx source
- frontend/src/components/atomic-crm/personas/persona-layout-regressions.test.ts:13-16,53 — counts source occurrences and forbids literal strings in PersonaList.tsx
- frontend/src/components/atomic-crm/projects/projects.css.test.ts:7-79, knowledge/knowledge-workspace-layout.test.ts:10-53, performance/performance.css.test.ts:6-59, kit/tailkit-system.css.test.ts:7-27, conversations/inbox/responsive-visual-regressions.test.ts:8-33 — five more files, ~80 further regex-against-CSS-source assertions
- frontend/src/components/atomic-crm/layout/mobile-workspace.test.tsx:41-101 — the converted exemplar: same concerns pinned via rendered getComputedStyle output
- backend/tests/test_external_source_sync_worker.py:93-97, test_external_source_sync.py:665-669, test_runtime_authority_stamps.py:54-59, test_security_headers.py:49-90, test_universal_platform_characterization.py:281-283 — backend tail (~13 sites) incl. a test asserting marker strings inside other test files' source

## Impact

Every styling pass or legit refactor of these components/stylesheets must edit byte-exact regexes in up to 14 test files; the raw pins also defeat minification/selector reordering and teach the suite to pass while real rendering breaks (text present ≠ rule applied). The backend meta-test couples CI to test-file wording, producing false failures during test refactors.

## Suggested fix

Two stages. (1) Freeze the class: convert the TSX-source assertions (settings.css, account-layout-regressions, persona-layout-regressions, knowledge-workspace-layout, backend test_universal_platform_characterization:281-283) to rendered-output or behavior assertions. (2) Batch the CSS-text pins (projects, performance, tailkit, responsive-visual-regressions, remaining settings/knowledge rules) into per-workspace rendered-layout specs following mobile-workspace.test.tsx, or fold genuinely global rules into the existing css-scoping ratchet. Delete the backend string pins in favor of the executed calls they describe.

## Notes

Closes the sweep-ledger TEST-10 tail item at its new, larger size — the ledger's ~30/7 figure is stale.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
