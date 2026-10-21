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

- Task: CHATBOT MOBILE REDESIGN — Lane 2: Inbox drill-down + Dashboard KPI + Leads/Contacts card list (deepseek consult 21/10).
- Scope: Phone surfaces only (<768px inbox, <md dashboard KPI, <640px leads list). Lane-1 files (`layout/Layout.tsx`, `layout/TopToolbar.tsx`, `layout/topbar/`, `components/application/app-navigation/`) untouched; `silversea` untouched. `layout/workspace-mobile-chat.css` IS in scope: it owns the open-phone-conversation height rule the keyboard inset must subtract from.
- Surface mapping note (decision recorded): the brief's "Leads/Contacts table" screens do not exist on this branch — `git log` shows `contacts/ContactList.tsx` and `leads/LeadCard.tsx`/kanban removed in earlier refactors (`c42822d4`, `121c6f5d`), and the static runtime registers only conversations/projects/settings/users. The live lead-record surface is the dashboard "Ứng viên mới" panel (rows open the conversation record), so the card-list + chips treatment landed there per the brief's field contract: Tên (title) · vị trí mong muốn (subtitle) · kỳ vọng lương (trailing, "giá trị deal") · `lead_stage` badge. ≥640px keeps the existing day-grouped rows ("giữ table").
- Files changed:
  - `frontend/src/hooks/use-visual-viewport.ts` (new) — VisualViewport keyboard inset.
  - `frontend/src/hooks/use-mobile.ts` — `useIsNarrow` (<640px) gate.
  - `frontend/src/components/atomic-crm/conversations/domain/phone-surface.ts` (+ `.test.ts`) (new) — inset math + swipe commit policy.
  - `frontend/src/components/atomic-crm/conversations/presentation/use-swipe-back.ts` (new) — edge-swipe back for the drill-down.
  - `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx` — keyboard-inset CSS var, swipe-back wiring, stable `backToList`.
  - `frontend/src/components/atomic-crm/conversations/ConversationContextPanel.tsx` — bottom-sheet class hooks.
  - `frontend/src/components/atomic-crm/conversations/inbox/context-drawer.css` — <md bottom sheet (drag handle, slide-up, reduced-motion guard).
  - `frontend/src/components/atomic-crm/conversations/inbox/mobile-layout.css` — keyboard-inset height subtraction + composer `max(12px, env(safe-area-inset-bottom))` padding.
  - `frontend/src/components/atomic-crm/layout/workspace-mobile-chat.css` — keyboard-inset height subtraction in the phone-chat expansion rule.
  - `frontend/src/components/atomic-crm/dashboard/kpiCards.ts` (+ `.test.ts`) (new) — pure KPI composition (period deltas, arrows, coverage guard).
  - `frontend/src/components/atomic-crm/dashboard/DashboardKpiCards.tsx` (+ `.test.ts`) (new) — 4-card strip.
  - `frontend/src/components/atomic-crm/dashboard/leadCardDirectory.ts` (+ `.test.ts`) (new) — pure filter/sort/chip policy.
  - `frontend/src/components/atomic-crm/dashboard/LeadCardList.tsx` (+ `.test.ts`) (new) — card list + sticky search + stage chips + sort control.
  - `frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx` — wires KPI strip (<md) and card list (<640px).
  - `frontend/src/components/atomic-crm/dashboard/dashboard.css` — KPI + lead-card styles (1col <sm, 2col sm–md, hidden ≥md).
  - `frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.render.test.tsx` — mock extended with `useIsNarrow`.
  - `frontend/qa/mobile-surfaces-shots.cjs` (new) — 390×844 evidence harness (real app, route-mocked API).
  - `qa/2026-10-21-mobile-surfaces/` — before/after PNG pairs.
- Instructions retrieved: `AGENTS.md` scoped workflow + task brief; `docs/development/code-standards.md` conventions followed (existing patterns reused: `useIsMobile` breakpoint hook style, `vitest-browser-react` render-test pattern, Cloudfone QA harness pattern for evidence).
- Approval required: No — no deploy/branch/PR operations requested or performed; the brief explicitly required commit + push on `feat-mobile-surfaces`.
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All three surfaces shipped: (1) inbox <768 list→drill-down (slide-in, back, edge swipe-back, sticky composer with `max(12px, env(safe-area-inset-bottom))`, VisualViewport keyboard inset, context bottom sheet, ≥768 layout untouched); (2) dashboard KPI strip — pipeline dark headline + new-leads delta vs previous period + conversion trend arrow + open conversations, 1col <sm / 2col sm–md / hidden ≥md ("giữ nguyên grid hiện tại"); (3) <640 leads card list + sticky search + scrollable stage chips + sort control (default newest), ≥640 keeps current rows. Evidence: `qa/2026-10-21-mobile-surfaces/before-{inbox-list,inbox-thread,inbox-context,dashboard,leads}.png` vs `after-*.png` at 390×844. |
| Diff is limited to the approved scope | PASS | `git status --short` shows only surface files + tests + QA harness + evidence; Lane-1 files (`Layout.tsx`, `TopToolbar.tsx`, `topbar/`, `app-navigation/`) and `silversea` untouched. `layout/workspace-mobile-chat.css` is the phone-chat surface rule (in scope; 2-line height change). |
| Protected operations were avoided or approved | PASS | No deploy/rollback/branch/PR; commit + push only, as the brief requested, to `feat-mobile-surfaces`. |
| Focused tests/checks pass | PASS | `pnpm exec vitest run --config vitest.config.ts --project app src/components/atomic-crm/dashboard src/components/atomic-crm/conversations` → 34 files, 320 tests passed (includes 26 new logic tests + 10 new render tests). |
| Broader regression tests pass when shared behavior changed | PASS | Shared inbox CSS/heights and `use-mobile` changed → full app suite: `pnpm exec vitest run --config vitest.config.ts --project app` → 127 files, 1094 tests passed. |
| Lint passes for affected code | PASS | `npx eslint --no-warn-ignored <all 18 affected files>` → 0 errors, 0 warnings (one `react-refresh` warning fixed by keeping the metrics query key module-private). |
| Type checking passes for affected code | PASS | `npm run typecheck` (`tsc --noEmit --project tsconfig.app.json`) → clean. |
| Build/import validation passes for affected code | PASS | `npm run build` (`tsc && vite build`) → success, bundle + service worker emitted. |
| Security and privacy impact reviewed | PASS | No secrets/PII logged or committed (QA fixtures are synthetic names/phones); VisualViewport hook reads only window metrics; no new network surface (KPI uses the existing `/api/v1/dashboard/metrics` endpoint). |
| Performance and async-I/O impact reviewed | PASS | Metrics query reuses the dashboard's TanStack contract (staleTime 30s / refetch 60s / gcTime 5min); lead filtering runs on the already-fetched 200 rows behind `useDeferredValue`; KPI rows/cards memoized on data identity; swipe-back attaches 4 passive listeners only while the phone drill-down is open; no avoidable per-render allocation (shared `EMPTY_CANDIDATES` sentinel). |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Chips are `role="group"` buttons with `aria-pressed`; sort trigger labelled "Sắp xếp: <mode>"; cards are real buttons with `Mở hội thoại với <tên>` labels (static rows keep `aria-label`); search input labelled; KPI strip is a labelled region; sheet has a grab handle + dialog semantics (existing); ≥40px touch targets for chips/search; `prefers-reduced-motion` disables the sheet slide; all copy Vietnamese. |
| Error handling and compatibility reviewed | PASS | `window.visualViewport` unsupported → inset 0 (layout unchanged); unknown/absent `lead_stage` → neutral badge + "Chưa có giai đoạn" (no throw); previous-period comparison degrades to "—" + "kỳ trước: 0" note instead of fabricated trends when the fetched rows do not cover the comparison window; metrics null-safe (`0` values while loading). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | No doc routing or link targets changed → `check-doc-links.mjs` N/A. `docs/product/codebase-summary.md` directory rows remain accurate at their level (dashboard = RecruitingCommandCenter with metric cards); the new phone-only treatment is recorded here and in the commit message. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added (grep of the diff). |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the intended surface files, tests, QA harness and `qa/2026-10-21-mobile-surfaces/` evidence are new/modified; no stray artifacts (`__screenshots__` failure artifacts removed). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  1. Keyboard-open composer behavior is proven by unit-tested inset math + CSS subtraction, not by a screenshot — headless Chromium has no IME/keyboard to emulate. Worth one manual device check (iOS Safari especially, where the overlay-keyboard case lives).
  2. Swipe-back is a cheap additive exit (Back button and browser history remain authoritative); the commit policy is unit-tested, the touch wiring is not e2e-tested.
  3. The brief's "Leads/Contacts" screens do not exist on this branch (see Task record); the card-list contract landed on the live leads surface (dashboard "Ứng viên mới" panel). If dedicated `/leads` + `/contacts` screens return later, `LeadCardList` + `leadCardDirectory.ts` are reusable as-is.
  4. KPI "so sánh kỳ trước" derives from the 200 most-recent leads the dashboard already fetches; if lead inflow ever exceeds 200 per 14 days the deltas will show "—" (coverage guard) rather than a wrong trend — extend with a date-filtered count endpoint if that happens.
