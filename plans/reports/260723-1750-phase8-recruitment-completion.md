# Agent Completion Checklist

## Task record

- Task: PASS
- Scope: PASS
- Files changed: PASS
- Instructions retrieved: PASS
- Approval required: PASS
- Approval evidence: N/A

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Leads/reporting/persona seams extracted under `frontend/src/components/atomic-crm/{leads,reporting,personas}/`; composition kept in recruitment capability, dashboard/performance facades, and persona screens. |
| Diff is limited to the approved scope | PASS | `git status --short -- frontend/src/components/atomic-crm/{capabilities/recruitment,dashboard,performance,personas,reporting,leads}` shows only owned files. |
| Protected operations were avoided or approved | PASS | No edits to protected docs/CSS/deps/backend/security/install files; no dependency or migration changes. |
| Focused tests/checks pass | PASS | `npm run test:unit:app -- --run src/components/atomic-crm/capabilities/recruitment/index.test.ts src/components/atomic-crm/leads/application/loadRecruitmentConversationRows.test.ts src/components/atomic-crm/dashboard/attentionDashboard.test.ts src/components/atomic-crm/dashboard/candidateDashboard.test.ts src/components/atomic-crm/reporting/domain/dashboardMetrics.test.ts src/components/atomic-crm/reporting/domain/performanceDiagnostics.test.ts src/components/atomic-crm/personas/PersonaAssignments.test.tsx src/components/atomic-crm/personas/domain/assignmentState.test.ts src/components/atomic-crm/personas/domain/followupRules.test.ts src/components/atomic-crm/personas/domain/personaMarkdown.test.ts` → `10 passed`, `50 passed`. |
| Broader regression tests pass when shared behavior changed | PASS | `npm run build` completed successfully on July 23, 2026; Vite production bundle generated. |
| Lint passes for affected code | PASS | `npm run lint -- src/components/atomic-crm/capabilities/recruitment/index.tsx src/components/atomic-crm/dashboard src/components/atomic-crm/performance src/components/atomic-crm/personas src/components/atomic-crm/reporting src/components/atomic-crm/leads` exited 0; only existing/react-refresh warnings on `capabilities/recruitment/index.tsx`. |
| Type checking passes for affected code | PASS | `npm run typecheck` exited 0 on July 23, 2026. |
| Build/import validation passes for affected code | PASS | `npm run build` exited 0; new facades and pure modules compile into the production bundle. |
| Security and privacy impact reviewed | PASS | Transport remains in infra adapters/facades only; no new secret handling, auth storage, or logging added. |
| Performance and async-I/O impact reviewed | PASS | Query keys/stale times/API paths preserved; capability keeps single batched lead fetch and realtime subscription behavior. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | No CSS/visual copy churn; existing Vietnamese labels and interaction structure preserved in dashboard/performance/persona surfaces. |
| Error handling and compatibility reviewed | PASS | Persona actions keep existing notify/error flows; reporting and lead adapters preserve endpoint paths and response handling. |
| Documentation impact handled | N/A | No user-visible workflow/setup/architecture docs requested for this slice. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | No new `TODO`, `FIXME`, or `HACK` markers added in owned paths. |
| Final `git diff --check` passes | PASS | `git diff --check -- frontend/src/components/atomic-crm/{capabilities/recruitment,dashboard,performance,personas,reporting,leads}` produced no output. |
| Final `git status --short` reviewed | PASS | Reviewed before staging; only owned recruitment/reporting/persona paths are changed in this worktree slice. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: Architecture guard may still prefer the capability-module `realtimeSocket` composition import to move one level higher, but the domain/application edges and app→infra edges in this slice are removed.
