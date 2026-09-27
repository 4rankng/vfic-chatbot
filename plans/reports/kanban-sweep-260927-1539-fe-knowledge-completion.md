# Kanban Sweep — FE-20 / FE-21 Completion Checklist (lane-fe-knowledge)

Copied from `standards/agent-completion-checklist.md` (template recovered from
git history — the parallel session's commit `65069078` deleted the `standards/`
tree mid-task; structure preserved below).

## Task record

- Task: Implement kanban cards FE-20 (gate KnowledgeSourceList 5s refresh
  poller on tab visibility) and FE-21 (fix orphaned poll chain in
  use-project-knowledge-catalog when two revisions are tracked).
- Scope: Poller visibility gating + poll-chain cancellation for the knowledge
  and project-knowledge surfaces, with regression tests, red-first for FE-21.
- Files changed:
  - `frontend/src/components/atomic-crm/knowledge/usePipelineAutoRefresh.ts` (new — visibility-gated 5s `useRefresh` interval hook)
  - `frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx` (inline poller effect replaced by the hook; unused `useEffect`/local `useRefresh` removed)
  - `frontend/src/components/atomic-crm/knowledge/usePipelineAutoRefresh.test.tsx` (new — 4 tests)
  - `frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts` (epoch-based chain cancellation + visibility pause/resume + processingKey reset on project change)
  - `frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.test.tsx` (new — 5 tests)
- Instructions retrieved: kanban cards FE-20/FE-21, `frontend/AGENTS.md`,
  `ExternalSourceList.tsx` + `ExternalSourceList.test.tsx` (pattern to mirror),
  `useResendCooldown.test.ts` / `useConversationRealtime.test.ts` (hook-test
  conventions), `knowledgePipelineUtils.ts`, `project-knowledge-service.ts`,
  domain contracts.
- Approval required: N/A — no protected paths touched (no migrations, webhooks,
  auth, prompts, dependency manifests, or deployment files).
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | FE-20: 5s `useRefresh` poller now disarms while `document.visibilityState === "hidden"` and re-arms on `visibilitychange` (mirrors ExternalSourceList's `refetchIntervalInBackground: false`). FE-21: a second `trackRevision` cancels the previous chain (epoch bump + `clearTimeout`), unmount/project switch cancels the live chain and drops in-flight results, hidden tab pauses hops until `visibilitychange`. |
| Diff is limited to the approved scope | PASS* | All files are poller/poll-chain files for FE-20/FE-21. One lane deviation: the lead's lane said "only files under `projects/`", but the FE-20 card's evidence pins `KnowledgeSourceList.tsx` at `atomic-crm/knowledge/` (the lead's message also described modifying it). Everything outside `projects/` stayed within `knowledge/`. (*deviation reported, not hidden) |
| Protected operations were avoided or approved | PASS | No commits/adds by this lane (note: the parallel session's commit `65069078` swept the worktree and captured this lane's files mid-flight — flagged to the lead; post-commit edits remain unstaged). No protected-path edits, no dependency changes. |
| Focused tests/checks pass | PASS | `npx vitest run src/components/atomic-crm/projects` → 13 files / 77 tests passed. Red-first proof for FE-21: with correct mocks the orphan test failed pre-fix with 22 `getCategories` calls vs 2 expected (orphan chain polled its full 40s budget after unmount); project-change and hidden-tab tests also failed pre-fix, all green post-fix. |
| Broader regression tests pass when shared behavior changed | PASS | `npx vitest run src/components/atomic-crm/knowledge` → 14 files / 52 tests passed (incl. `KnowledgeSourceList.test.tsx`). |
| Lint passes for affected code | PASS | `npx eslint` on the five touched files → exit 0, no findings. |
| Type checking passes for affected code | PASS | `npm run typecheck` → zero errors in touched files. Remaining errors are in `personas/PersonaForm.test.tsx`, an in-flight file of the parallel session, not this lane. |
| Build/import validation passes for affected code | N/A | Vitest browser-mode transform + typecheck cover imports; no build-relevant changes (no new deps, no entry points). |
| Security and privacy impact reviewed | N/A | Polling cadence only; no auth, no secrets, no message/PII content logged. |
| Performance and async-I/O impact reviewed | PASS | This is the performance fix: no backend refetches from hidden tabs (FE-20), no duplicate poll chains after upload-then-replace (FE-21). All I/O remains async; timers cleaned up on every path. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No markup, focus, or copy changes; the "Đang xử lý, tự làm mới mỗi 5 giây" pill is unchanged and remains accurate for a visible tab. |
| Error handling and compatibility reviewed | PASS | Hook return shape and public behavior unchanged; success/FAILED/give-up notify branches preserved verbatim (pinned by tests 1-2). In-flight hop results after cancellation are discarded instead of touching state; a stale chain's fetch failure can no longer clear the new chain's `processingKey`. |
| Documentation impact handled | N/A | Internal polling behavior fix matching the wave-1 ExternalSourceList precedent (which added no docs); no setup/command/architecture/security change. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Grep across the five touched files → no matches. |
| Final `git diff --check` passes | PASS | Exit 0. |
| Final `git status --short` reviewed | PASS | Remaining unstaged: my two test files (post-commit renderHook typing fix) plus the parallel session's `.claude/CLAUDE.md` and untracked `PersonaForm.test.tsx` — none staged by this lane. |

## Result

- Overall status: DONE (with two flags for the lead: lane path deviation on
  FE-20, and the parallel session committing lane files in `65069078`).
- Remaining risks or follow-ups: None for the cards themselves. Optional
  follow-up: the knowledge list still re-arms its interval on every refetch
  (new `sources` array identity restarts the 5s window) — pre-existing
  cadence behavior, out of scope.
