# Agent Completion Checklist

## Task record

- Task: Redesign the AI Providers settings panel for clarity and polish, and fix
  the missing conversation-list avatar on Messenger rows.
- Scope: Frontend only — the AI Providers panel markup/styles in
  `ZaloIntegrationPage.tsx` + `settings.css`, and the recruitment row
  presentation used by the inbox list and thread header.
- Files changed:
  - `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx`
  - `frontend/src/components/atomic-crm/integrations/settings.css`
  - `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.navigation.test.tsx`
  - `frontend/src/components/atomic-crm/leads/domain/recruitmentPresentation.ts`
  - `frontend/src/components/atomic-crm/leads/application/loadRecruitmentConversationRows.ts`
  - `frontend/src/components/atomic-crm/leads/application/loadRecruitmentConversationRows.test.ts`
  - `frontend/src/components/atomic-crm/capabilities/recruitment/index.test.ts`
- Instructions retrieved: root `AGENTS.md`, `frontend/AGENTS.md`, and the
  existing panel/presentation sources and their tests.
- Approval required: Yes — reading `CredentialSecretField.tsx` was gated by the
  privacy hook; the redesign scope was also put to the user.
- Approval evidence: User answered "Yes, approve access" to the file-access
  prompt and "do whatever you need" to the scope question.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Panel rebuilt as one ranked board; avatar/name now resolve on Messenger rows. Rendered and inspected via a temporary Playwright harness (since removed). |
| Diff is limited to the approved scope | PASS | `git status --short` lists only the 7 files above. No backend, migration, or dependency changes. |
| Protected operations were avoided or approved | PASS | No changes to `backend/app/core/*`, webhooks, migrations, deployment files, `frontend/src/index.css`, or dependency manifests. |
| Focused tests/checks pass | PASS | `npm run test:unit:app -- --run src/components/atomic-crm/integrations` → 5 files, 41 tests passed. |
| Broader regression tests pass when shared behavior changed | PASS | `npm run test:unit:app -- --run` → 106 files, 564 tests passed. Needed because `recruitmentPresentation.ts` is shared by the inbox list and the thread header. |
| Lint passes for affected code | PASS | `npm run lint` → clean (no output). |
| Type checking passes for affected code | PASS | `npm run typecheck` → clean. |
| Build/import validation passes for affected code | PASS | `npm run build` → production bundle generated, 93 precache entries. |
| Security and privacy impact reviewed | PASS | No credential handling changed. Provider test errors are now summarised in the visible label with the raw upstream text moved to a `title` tooltip — same data, no new exposure, and no secret is ever in that string. |
| Performance and async-I/O impact reviewed | PASS | `loadRecruitmentConversationRows` now skips the lead fetch instead of the whole presentation pass when no Zalo id is present, so the Messenger-only inbox issues strictly fewer requests than the Zalo path, not more. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Reorder buttons carry explicit Vietnamese `aria-label`s ("Tăng/Giảm ưu tiên cho X"); rank badges are `aria-hidden` because the order line states the same thing in text. Copy stays Vietnamese-only. `:focus-visible` outlines retained on the new controls; touch targets unchanged. |
| Error handling and compatibility reviewed | PASS | `describeProviderTestError` falls through to the operator's own text when no pattern matches, so an unknown failure is never swallowed. Save payloads, API contracts, and the stored failover ranking are untouched. |
| Documentation impact handled | N/A | No user-facing setup, command, contract, or architecture change — a settings panel layout and a presentation-layer bug fix. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff` contains none. |
| Final `git diff --check` passes | PASS | `git diff --check` → no output. |
| Final `git status --short` reviewed | PASS | 7 modified files, no untracked leftovers (the temporary visual harness and its PNG were deleted). |

## Result

- Overall status: PASS — shipped as cec3057c + f1a9fd13, deployed to prod as ghcr.io/4rankng/tinghire-fe:f1a9fd13
- Remaining risks or follow-ups:
  - The avatar fix was verified by unit tests, not against a live Messenger
    conversation. Worth a quick look in the running app.
  - `.settings-group-icon:has(.settings-llm-rank)` uses `:has()`. It is
    Baseline-supported and consistent with the sheet's existing use of
    `color-mix()` and container queries, but it is the newest selector in the
    file.
