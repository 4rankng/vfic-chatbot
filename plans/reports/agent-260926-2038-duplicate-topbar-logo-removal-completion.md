# Agent Completion Checklist — duplicate topbar logo removal

## Task record

- Task: Remove the duplicated small TingHire mark that appeared beside the
  sidebar rail logo at tablet widths (user-reported screenshot, 768–1020 px
  band).
- Scope: Hide `.workspace-topbar-brand` from 768 px up so the rail mark is the
  only brand on desktop/tablet; phones (<768 px) keep the topbar brand with
  the "TingHire" text. Test updated to the new invariant.
- Files changed:
  - `frontend/src/components/atomic-crm/layout/desktop-workspace.css` —
    `display: none` for `.workspace-topbar-brand` inside the existing
    `@media (min-width: 768px)` block, with the reason in a comment.
  - `frontend/src/components/atomic-crm/layout/mobile-workspace.test.tsx` —
    tablet section now asserts the topbar brand is hidden at 900 px; dropped
    three dead img-style assertions on the now-hidden element and its orphaned
    variable.
- Instructions retrieved: root `AGENTS.md`, `frontend/AGENTS.md`, layout CSS
  and tests in `layout/`, `css-scoping.test.ts` ratchet mechanics.
- Approval required: none obtained, none needed — `frontend/src/index.css`
  (protected) was deliberately NOT edited; the fix lives in the non-protected
  layout sheet. No migrations, security, prompts, or dependencies touched.
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Root cause: index.css hides the topbar brand only at ≥1021 px while the rail shows from ≥768 px, so 768–1020 px rendered both marks. New rule hides the topbar brand ≥768 px; mobile keeps logo + text. |
| Diff is limited to the approved scope | PASS | `git diff --stat`: 2 files, +9/−5, layout CSS + its test only. |
| Protected operations were avoided or approved | PASS | Protected `index.css` untouched (root fix one-liner there would also work but requires approval; layout sheet wins the cascade because index.css loads first from `main.tsx:3`). |
| Focused tests/checks pass | PASS | `npx vitest run css-scoping.test.ts Header.test.tsx mobile-workspace.test.tsx` → 11 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Same run covers the shared shell CSS consumer tests; FE-19 ratchet included (rule added is not a `.inbox-bg-container` descendant, count unchanged). |
| Lint passes for affected code | PASS | `npx eslint src/components/atomic-crm/layout/mobile-workspace.test.tsx` clean. |
| Type checking passes for affected code | PASS | `npm run typecheck` (tsc --noEmit, tsconfig.app.json) clean. |
| Build/import validation passes for affected code | PASS | Vitest transform+import of both touched modules succeeded in the same run. |
| Security and privacy impact reviewed | N/A | Presentation-only CSS/test change; no data, auth, or transport surface. |
| Performance and async-I/O impact reviewed | N/A | No JS/CSS runtime cost beyond one display rule. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Markup and aria-labels untouched; rail brand link keeps `aria-label="TingHire - về trang tổng quan"`. No text changes. |
| Error handling and compatibility reviewed | PASS | Phones (<768 px) and wide desktop (≥1021 px) behavior unchanged; only the duplicated band changes. |
| Documentation impact handled | N/A | Visual defect fix; no user-facing workflow, command, or contract change. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the two intended files modified; the untracked report from the earlier release-gate session remains, untouched. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: The `index.css:1209` band rule that clips the
  "TingHire" span at 768–1020 px is now dead styling (brand hidden there) —
  harmless; fold it away the next time index.css is legitimately open for
  approved edits. Deployed environments need the next deploy to see the fix.
