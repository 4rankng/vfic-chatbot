# Completion checklist — Zalo settings page rename

Copied from `standards/agent-completion-checklist.md`.

## Task record

- Task: Investigate the Repowise code-health report for
  `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx` (5.5/10,
  10 findings); act on the verified subset; then commit and push (user, 2026-09-27).
- Scope: Investigation + the one real defect (name/role misnomer) + Repowise
  bookkeeping + records. Out of scope (untouched): directory rename, `renderSection`
  split, test-connection-button extraction, `index.css` protected-path comment.
- Files changed: `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx`
  → `SettingsConsolePage.tsx`, `ZaloIntegrationPage.navigation.test.tsx` →
  `SettingsConsolePage.navigation.test.tsx` (+15 JSX sites, screenshots dir), `integrations/index.tsx`,
  `integrations/settings.css.test.ts`, `frontend/registry.json` (registry:gen, 2 entries),
  reports under `plans/reports/`, repowise decision record. Memory file outside repo.
- Instructions retrieved: root + frontend AGENTS.md, `.claude/rules/*`, ai-slop-cleaner
  SKILL.md, `plans/260921-2227-settings-provider-panel/plan.md` (via Explore agents).
- Approval required: none triggered — no alembic/webhook/auth/prompt/deployment edits;
  protected `frontend/src/index.css` left untouched (stale comment flagged as follow-up).
- Approval evidence: plan approved via ExitPlanMode; commit+push requested mid-turn.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Rename + dependents landed in `54a34b58`; investigation report + this checklist written |
| Diff is limited to the approved scope | PASS | 5 files, 26+/26−; registry.json regeneration is CI-mandated (`registry:check` fails on the missing old path); zero other files touched |
| Protected operations were avoided or approved | PASS | No protected-path edits; `index.css:432` stale comment deliberately left for a maintainer |
| Focused tests/checks pass | PASS | Targeted vitest 3 files, 25/25 (executor report `plans/reports/executor-260927-1048-zalo-settings-rename.md`) |
| Broader regression tests pass when shared behavior changed | N/A | No shared behavior or contract changed — rename only; navigation test exercises the full console render path |
| Lint passes for affected code | PASS | `npm run lint` exit 0 |
| Type checking passes for affected code | PASS | `npm run typecheck` exit 0 |
| Build/import validation passes for affected code | PASS | Typecheck + `npm run registry:check` ("Registry paths and local text dependencies are complete (251 files)") |
| Security and privacy impact reviewed | N/A | Rename only; no auth/secret/PII surface touched |
| Performance and async-I/O impact reviewed | N/A | No runtime code path changed |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No markup, copy, or class changes |
| Error handling and compatibility reviewed | N/A | No error paths touched |
| Documentation impact handled | PASS | No evergreen docs reference the old filename (frontend AGENTS.md resource table names directories only); investigation report is the durable record |
| No new unlinked TODO/FIXME/HACK | PASS | Executor sweep clean; no new markers introduced |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors) |
| Final `git status --short` reviewed | PASS | Remaining: repowise marker `.claude/CLAUDE.md` (repowise-generated, committed per convention as its own chore) + docs commit |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: `frontend/src/index.css:432` comment still reads
  "ZaloIntegrationPage's" (protected path — one-line maintainer edit on next approval);
  `ZaloIntegrationPage.test.ts` filename is a residual minor misnomer (tests
  `buildZaloUpdatePayload`, never the page); optional test-connection-button extraction
  only if a refreshed Repowise report re-flags DRY in `integrations/`.
