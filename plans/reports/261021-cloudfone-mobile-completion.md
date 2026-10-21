# Completion — Cloudfone transcripts mobile 390px (table→card list)

- Task: Fix `CloudfoneTranscriptsSection` mobile UX at 390px — swap the desktop
  data table for a card list below 640px, stack the filter bar, compact pager,
  keep the desktop table unchanged (QA screenshot 21/10).
- Scope: `frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.tsx`,
  its unit test, QA harness + evidence under `frontend/qa/` and
  `qa/2026-10-21-cloudfone-mobile/`.
- Files changed:
  - `frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.tsx`
  - `frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.test.tsx`
  - `frontend/qa/cloudfone-mobile-harness.html` (new, QA-only)
  - `frontend/qa/cloudfone-mobile-harness.tsx` (new, QA-only)
  - `frontend/qa/cloudfone-mobile-shots.cjs` (new, evidence capture)
  - `qa/2026-10-21-cloudfone-mobile/{before,after}-{list,transcript}.png` (new)
- Instructions retrieved: `AGENTS.md`, `frontend/AGENTS.md` § UI/UX Component
  Sourcing (Untitled UI primitives, no new libraries, `data-allow-tall` contract
  in `src/index.css` §3).
- Approval required: none (user brief IS the approval; no deploy/PR).
- Approval evidence: user brief in session, 2026-10-21.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Card list <640px (phone+duration badge, datetime+"đã lưu", card=button, ring+bg selected), stacked full-width filters w/ search icon, compact Trước/Sau + `1/1` pager, transcript panel full-width with SĐT·duration·close header and `break-words` text; desktop table byte-for-byte unchanged (same `Table` markup inside `isPhone ?` branch). Evidence: `qa/2026-10-21-cloudfone-mobile/after-*.png` vs `before-*.png`. |
| Diff is limited to the approved scope | PASS | Only the two component files + QA harness/evidence. Silversea untouched (`git status` shows no silversea paths). |
| Protected operations were avoided or approved | PASS | No deploy/commit-to-main/PR/branch operations beyond the requested commit+push on `fix-cloudfone-mobile`. |
| Focused tests/checks pass | PASS | `pnpm exec vitest run --project app src/.../CloudfoneTranscriptsSection.test.tsx` → 9/9 passed (desktop 5 pre-existing behaviors + phone card list, stacked filters/compact pager, desktop parity, Xóa lọc gating). |
| Broader regression tests pass when shared behavior changed | N/A | No shared module changed; component is self-contained (only consumer `SettingsConsolePage.tsx` untouched). |
| Lint passes for affected code | PASS | `pnpm exec eslint` on both changed files → clean. |
| Type checking passes for affected code | PASS | `pnpm exec tsc --noEmit --project tsconfig.app.json` → exit 0. |
| Build/import validation passes for affected code | PASS | Vitest browser project compiled and rendered the component in Chromium (same Vite pipeline); no new imports beyond `useSyncExternalStore` (React core). |
| Security and privacy impact reviewed | PASS | No new endpoints, no secrets/PII logged; transcript content rendering unchanged (text-only, no `dangerouslySetInnerHTML`). |
| Performance and async-I/O impact reviewed | PASS | One `useSyncExternalStore` matchMedia subscription (shared query fn, no re-render storm); queries unchanged (`staleTime` 30s/300s). Card list is plain DOM, lighter than the React Aria table it replaces on phones. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Card list `role="list"`/`listitem` + `aria-selected` mirrors the old row selection; cards are real `<button>`s (keyboard focusable, `outline-focus-ring`); pager buttons ≥44px touch target and Prev disabled on page 1; transcript close has `aria-label="Đóng bản ghi"`; `aria-live` page counter. Vietnamese copy per brief. Visual proof in AFTER screenshots. |
| Error handling and compatibility reviewed | PASS | Pending skeleton, error `EmptyState` + retry, empty state with conditional "Xóa lọc" — all shared paths untouched and still rendered above the surface swap. `useSyncExternalStore` getServerSnapshot returns false (SSR-safe). |
| Documentation impact handled | N/A | No user-visible docs, setup, commands, architecture or public contracts changed; agent routing files untouched, so `check-doc-links` not required. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff` contains none. |
| Final `git diff --check` passes | PASS | Ran before commit — no whitespace errors. |
| Final `git status --short` reviewed | PASS | Only intended files staged; `frontend/node_modules` symlink is untracked (ignored). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The surface swap keys off `matchMedia("(max-width: 639px)")` (window width)
    rather than container width — correct for this full-bleed settings page,
    would need rework if the section ever mounts in a narrow drawer on a wide
    window.
  - Vitest browser project compiles no Tailwind, so layout classes are asserted
    structurally (classList) not via computed width; real-pixel evidence is the
    Playwright BEFORE/AFTER screenshots instead.
