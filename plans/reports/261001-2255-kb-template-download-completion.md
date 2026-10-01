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

- Task: Fix the KB template download and name the button Tải mẫu KB.
- Scope: Authenticated text-download repair verification, exact label, HTTP/OpenAPI consistency, browser/API regressions and portable patch delivery.
- Files changed: See 261001-2255-kb-template-download.md and full/incremental manifests.
- Instructions retrieved: Root/frontend AGENTS, code/testing conventions, review checklist and this sixteen-gate template.
- Approval required: N/A — local repair and patch delivery directly authorized; protected operations avoided.
- Approval evidence: User requested the download fix, exact Tải mẫu KB label and concise wording.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Full patch includes raw-text download handling; exact button label and HTTP/OpenAPI response agree; both patch paths apply-verified. |
| Diff is limited to the approved scope | PASS | Latest changes limited to download label/contracts/tests/docs; prior authorized work preserved. |
| Protected operations were avoided or approved | PASS | No branch/commit/push/PR/merge/deploy, database migration or dependency update. |
| Focused tests/checks pass | PASS | 60 focused frontend tests; 39 backend template/export/architecture checks; 6 actual desktop/mobile E2E cases. |
| Broader regression tests pass when shared behavior changed | PASS | 896 frontend tests across 118 files; backend runtime serialization unchanged, focused route and architecture regressions passed. |
| Lint passes for affected code | PASS | Scoped ESLint and backend Ruff passed. |
| Type checking passes for affected code | PASS | Frontend app+Node TypeScript passed; backend API Pyright: 0 errors and 0 warnings. |
| Build/import validation passes for affected code | PASS | Production build and built-browser smoke passed. |
| Security and privacy impact reviewed | PASS | Recruiter/admin authentication and project validation retained; no PII logs, secret exposure, new egress or token-bearing URLs. |
| Performance and async-I/O impact reviewed | PASS | Existing async text fetch, cancellation and attachment lifecycle preserved; no new DB/provider work. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Exact short Vietnamese label; real mouse, keyboard and mobile touch downloads verified at 390/900/1440px. |
| Error handling and compatibility reviewed | PASS | Text and MIME validation, filename fallback, empty response/error retry and project-change cancellation retained; downloaded bytes verified. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | API/workflow docs updated; routing checker passes for 32 paths, 4 targets and 4 documents. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Latest implementation diff reviewed; no added TODO/FIXME/HACK markers. |
| Final `git diff --check` passes | PASS | Final whitespace and fresh-tree patch whitespace checks passed. |
| Final `git status --short` reviewed | PASS | HEAD/index/status preserved by artifact exporters; only owned test containers removed; all source edits remain uncommitted. |

## Result

- Overall status: PASS — implemented, verified and packaged.
- Remaining risks or follow-ups: Local desktop/mobile Chrome downloads verified; no live-production or WebKit/Firefox proof. See report.
