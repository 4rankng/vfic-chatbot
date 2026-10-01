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

- Task: Training, retrieval, native status and twelve-category migration patch handoff
- Scope: Authorized implementation and portable cumulative/incremental patches; immediate wrap-up requested
- Files changed: See cumulative and incremental export manifests/diffstats; prior authorized changes included
- Instructions retrieved: AGENTS.md; frontend/AGENTS.md; architecture, code standards, testing, review and completion sources
- Approval required: None for local code/test/export; protected operations excluded
- Approval evidence: User requests implementation and full Git patch; latest instruction explicitly requests wrap-up now

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Code and full patch prepared for review; known verification limits stated in the task report. |
| Diff is limited to the approved scope | PASS | Training/retrieval/status/migration changes plus prior authorized cumulative work; existing changes preserved. |
| Protected operations were avoided or approved | PASS | No branch, commit, push, PR, deployment, production migration or real message. |
| Focused tests/checks pass | PASS | 98 training,116 retrieval,262 status,88 migration units;51+14+11+3 PostgreSQL lane cases;111 domain and33 panel tests. |
| Broader regression tests pass when shared behavior changed | BLOCKED | Immediate user wrap-up: backend interrupted at2336passed/30skipped; final entire suites not rerun after late migration. See task report. |
| Lint passes for affected code | PASS | Whole backend Ruff, scoped frontend lint and formatting pass; full frontend0errors/35existing warnings. |
| Type checking passes for affected code | PASS | Backend Pyright0errors/0warnings; frontend TypeScript and migration scope checks pass. |
| Build/import validation passes for affected code | PASS | Production frontend build and built-bundle login smoke pass; backend architecture/import and typing checks pass. |
| Security and privacy impact reviewed | PASS | Scoped active ownership gates; bounded status and safe failure receipts/logs; no token/message/recipient leakage added. |
| Performance and async-I/O impact reviewed | PASS | Off-loop extraction/storage; source fallback within existing model-call ceiling; bounded evidence and status requests. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Reused existing migration components/controls; Vietnamese copy and panel behavior verified; no layout redesign. |
| Error handling and compatibility reviewed | PASS | SQL rollback/retry, empty/degraded retrieval, status lifetime, legacy cadence settings and migration preservation tested. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | Workflow/API/architecture/troubleshooting updated; routing validates32paths/4targets. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | No new task markers in this change; frozen source reviewed. |
| Final `git diff --check` passes | PASS | Whitespace check and exported private-index patch check pass. |
| Final `git status --short` reviewed | PASS | Worktree/HEAD/real index preserved; task-owned test services cleaned; exports ignored. |

## Result

- Overall status: BLOCKED for full regression certification; patch handoff requested by user
- Remaining risks or follow-ups: Run entire final backend/frontend suites before release; live provider behavior remains unverified. See companion report.
