# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

Restored 2026-09-27 (DOC-19) after `65069078` deleted it. The 2026-09-27 sweep
had to reconstruct these sixteen gates from the previous sweep's report because
this file was gone; the gate list is meant to live here, not in the most recent
report. Do not renumber or drop gates when filling one in — a report that omits a
gate is a report that was not filled from this file.

## Task record

- Task: Remove the per-category Tải mẫu action and refresh portable Git patches.
- Scope: Category button, dead download hook members, related Vietnamese guidance, component regression and workflow documentation; previous authorized changes preserved.
- Files changed: See 261001-2246-remove-category-template.md; incremental patch has four source/doc paths plus report and completion.
- Instructions retrieved: Root/frontend AGENTS, implementation/testing conventions, review checklist and this sixteen-gate template.
- Approval required: N/A — user explicitly requested the local button removal and patch delivery; protected operations avoided.
- Approval evidence: User: remove button tai mau which give me stupid jobs id yaml template.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Exact category template button and dead download logic removed; both patch paths apply-verified on fresh trees. |
| Diff is limited to the approved scope | PASS | Four implementation/test/doc files plus two task records; prior audit preserved. Separate Project actions unchanged. |
| Protected operations were avoided or approved | PASS | No branch/commit/push/PR/merge/deploy or database/dependency changes. |
| Focused tests/checks pass | PASS | 45 focused Chromium component tests; published/empty button absence and inline editing covered. |
| Broader regression tests pass when shared behavior changed | PASS | 896 frontend tests across 118 files passed; backend is unchanged and its prior evidence is preserved. |
| Lint passes for affected code | PASS | Scoped ESLint passes for all three touched frontend files. |
| Type checking passes for affected code | PASS | Frontend app TypeScript passes; no unknown consumers of removed hook members. |
| Build/import validation passes for affected code | PASS | Production build and built-browser smoke pass. |
| Security and privacy impact reviewed | PASS | No auth, storage, egress or logging changes; existing project export behavior preserved. |
| Performance and async-I/O impact reviewed | PASS | Removed browser attachment logic/state; existing async reads and inline editing unchanged. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Obsolete action and three instructions removed; existing semantic edit controls and Vietnamese guidance tested in Chromium. |
| Error handling and compatibility reviewed | PASS | Source read failure/retry/save/cancel/publication tests pass; internal new-category seeding remains covered. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | KB workflow updated; routing checker confirms 32 paths, 4 targets and 4 documents. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Incremental implementation diff reviewed: no new TODO/FIXME/HACK markers. |
| Final `git diff --check` passes | PASS | Git diff whitespace and fresh-tree patch whitespace checks pass. |
| Final `git status --short` reviewed | PASS | Final status reviewed; HEAD/index/status preserved by exporters; source remains unstaged/uncommitted. |

## Result

- Overall status: PASS — implemented, verified, documented and packaged with fresh-tree apply checks.
- Remaining risks or follow-ups: No production or live-provider checks; backend unchanged. Full-project template/export retained as separate actions. See report.
