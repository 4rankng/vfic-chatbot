# Agent Completion Checklist

## Task record

- Task: Complete Phase 7 of the incremental DDD/layered rearchitecture.
- Scope: Frontend conversation presentation, application ports/use cases, domain rules, infrastructure adapters, runtime reset, compatibility facades, architecture guards, and conversation E2E coverage.
- Files changed: `frontend/src/components/atomic-crm/conversations/`, REST API compatibility facade, framework-neutral API client, human-reply compatibility service, E2E specification, E2E harness, and architecture tests.
- Instructions retrieved: `AGENTS.md`, `.claude/skills/implement-change/SKILL.md`, `.claude/skills/verify-change/SKILL.md`, `docs/testing.md`, `standards/definition-of-done.md`, and Phase 7 plan.
- Approval required: Yes for the cross-cutting architecture and production rollout.
- Approval evidence: User requested the full incremental DDD rearchitecture, deployment, monitoring, and blanket approval except genuine design decisions.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Conversation feature uses explicit domain/application/infrastructure/presentation boundaries with stable public facades. |
| Diff is limited to the approved scope | PASS | Changes are limited to the Phase 7 conversation slice, its shared API seam, architecture guard, and owned E2E harness. |
| Protected operations were avoided or approved | PASS | No secrets, migrations, deployment files, auth policy, webhook behavior, bot policy, or dependencies changed. |
| Focused tests/checks pass | PASS | Conversation/repository/domain/compatibility focused lanes passed; reconnect success, later-page failure, and unmount race regressions included. |
| Broader regression tests pass when shared behavior changed | PASS | Backend: 2205 passed, 23 skipped. Frontend: 418 passed across 78 files. |
| Lint passes for affected code | PASS | Frontend `npm run lint`; backend `.venv/bin/ruff check .`. |
| Type checking passes for affected code | PASS | Frontend `npm run typecheck`. |
| Build/import validation passes for affected code | PASS | Frontend `npm run build`; backend `.venv/bin/python -c "import app.main"`. |
| Security and privacy impact reviewed | PASS | Token/permission contracts preserved; no secrets, PII, or message content logging added. |
| Performance and async-I/O impact reviewed | PASS | Existing virtualization retained; reconnect paging is bounded per request and cursor-progress guarded; no blocking production I/O added. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Existing UI/strings retained; browser E2E uses accessible roles and validates the real transcript and mode controls. |
| Error handling and compatibility reviewed | PASS | Legacy imports remain facades; direct human-reply import is deterministic; stale async completions are fenced; room rejoin and exhaustive gap-fill are covered. |
| Documentation impact handled | PASS | Phase status and completion evidence are updated; no public API or setup documentation changed. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Scoped search found no new markers. |
| Final `git diff --check` passes | PASS | `git diff --check` returned no errors. |
| Final `git status --short` reviewed | PASS | Only the Phase 7 implementation and completion report are present in the isolated worktree. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: Production frontend deployment and post-deploy monitoring are the remaining rollout actions; Phase 8 follows after Phase 7 is clean in production.
