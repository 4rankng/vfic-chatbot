# Agent Completion Checklist — settings mobile overhaul

Copy of `standards/agent-completion-checklist.md`, filled 2026-10-22 02:10 ICT.

## Task record

- Task: SETTINGS MOBILE OVERHAUL + transcript bottom-sheet, per
  `/tmp/silversea-army2/consult-settings-mobile.md` (deepseek consult 21/10)
- Scope: frontend only — settings drill-down (<768px), Cloudfone transcripts
  phone surface, shared bottom sheet, S1/S2 conversation bubbles. Exclusions
  honored: no backend changes, no silversea files touched.
- Files changed: `frontend/src/components/application/bottom-sheet/bottom-sheet.tsx`
  (+ test, new), `integrations/CloudfoneTranscriptsSection.tsx` (+ test),
  `integrations/cloudfone-transcripts.css` (new),
  `integrations/TranscriptConversation.tsx` (new),
  `integrations/transcript-utterances.ts` (+ test, new),
  `integrations/SettingsChrome.tsx`, `integrations/SettingsMobileGroups.tsx`
  (new), `integrations/SettingsConsolePage.tsx` (+ nav test),
  `integrations/settingsNav.ts`, `integrations/settings.css`,
  `integrations/useSettingsBundle.ts`, `integrations/CloudfoneSection.tsx`,
  `integrations/EmailDigestSection.tsx`,
  `integrations/settings-workspace-layout.test.tsx`,
  `users/UserList.test.tsx`, `plans/qa-261021/settings-mobile-evidence.mjs`
  (new), `plans/qa-261021/settings-mobile-seed.sql` (new),
  `qa/2026-10-21-settings-mobile/*` (evidence).
- Instructions retrieved: brief + consult doc (read before code), AGENTS.md
  routed sources (code-standards via conventions in place), repo test/CSS
  conventions (control envelope `src/index.css` §3, UUI token layer,
  vitest browser lane).
- Approval required: no (explicit brief = approved scope; commit+push mandated).
- Approval evidence: brief instructs "implement đúng TỪNG BƯỚC spec + tests +
  commit+push. NO question tools."

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | A: drill-down root 3 grouped cards + sub-pages + sticky app bar (‹ + 17px/600 title), desktop rail untouched. B: sticky search 44px/r10 debounce 300ms + 32px day-scope chips + bordered call cards (name 16/600, duration 14 gray-500, preview 14 gray-600, time 13 gray-400, badge 12/500 "đã lưu"), card = tap target. C: shared `BottomSheet` (slide-up, 50%→90% drag detents, 32×4 gray-300 grip, 40% scrim tap-to-close, aria-modal + React Aria focus trap) replaces the panel <768; panel kept ≥768. D: S1 gray-100 left / S2 brand-50 right bubbles, 15px/1.7 text, 13/600 labels, 8px gaps, ≤80% width, per-utterance 44px copy + header copy-all, `aria-label="Speaker: X. …"`. Evidence: `qa/2026-10-21-settings-mobile/after-*.png` (6 flow steps) + `after-driver.log` geometry asserts (row 49px∈[44,56], back 44×44, search 44, chip 32, sheet 422px→760px, bubble 136px≤80%, scrim tap closes). |
| Diff is limited to the approved scope | PASS | `git status --short`: 12 modified + 7 new paths, all frontend settings/transcripts + QA artifacts. No backend, no silversea. |
| Protected operations were avoided or approved | PASS | No deploy/merge/branch; the single commit+push is the brief's mandate. Dev-DB edits were evidence plumbing (below). |
| Focused tests/checks pass | PASS | `npx vitest run --project app src/components/atomic-crm/integrations/ src/components/atomic-crm/users/UserList.test.tsx src/components/application/bottom-sheet/ src/components/atomic-crm/kit/` → 157/157 (18 files). |
| Broader regression tests pass when shared behavior changed | PASS | Same sweep covers the shared chrome: navigation suite (21), workspace-layout (measured CSS), UserList (embedded rows), transcripts (19), sheet (3), parser (5). Desktop surfaces verified unchanged by the kept desktop tests (table/panel/filter-form assertions pass unmodified). |
| Lint passes for affected code | PASS | `npm run lint` → 0 errors; 35 warnings, all pre-existing `react-refresh` patterns (the 2 this lane introduced were removed by moving query keys into `integrationSettingsKeys`). |
| Type checking passes for affected code | PASS | `npm run typecheck` → 0 errors. |
| Build/import validation passes for affected code | PASS | `npm run build` → `dist/` generated without errors. |
| Security and privacy impact reviewed | PASS | No secrets/PII logged (structured logging untouched); transcripts render only from the existing admin API; clipboard copies are user-gesture `navigator.clipboard.writeText` with toast feedback (the `credentialClipboard` helper); no new data exposure vs the desktop table. |
| Performance and async-I/O impact reviewed | PASS | Search debounced 300ms (one query per pause, not per keystroke); root toggles reuse the sections' query keys + `setQueryData` (no duplicate fetch storms); sheet drag mutates one inline height with snap-to-nearest (no per-move layout of the list); I/O stays on the existing async query layer. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | aria-modal + focus containment + Escape + scrim dismiss (verified live in evidence log); `aria-label="Speaker: …"` per bubble; native radio-group chips (single-select semantics); touch targets: rows 48px (measured 49), icon actions 44px (documented `max-height: none` opt-out), search 44px, grip drag zone; contrast near-black ink (`--color-text-primary`) on neutral-100/brand-50 ≥ 4.5:1; all copy Vietnamese. |
| Error handling and compatibility reviewed | PASS | Pending/error/empty states preserved on both surfaces; toggle saves toast on failure; ≥768 keeps the exact pre-existing table/panel/filter form; `useIsMobile` (768) is now the single surface seam; back rule: transcripts → Cloudfone → root. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | No routed doc describes this surface (checked `docs/product/codebase-summary.md` etc.); no link targets changed → check-doc-links N/A. Consult deviations documented in code comments + "Remaining risks" below. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK"` over all new/changed feature files → none. |
| Final `git diff --check` passes | PASS | No whitespace errors. |
| Final `git status --short` reviewed | PASS | Only the intended files listed (12 modified, 7 new paths); throwaway probes removed (`width-probe.mjs`, `*-failed.png`). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Data-constrained deviations from the consult (documented in code):
    chips map to the real single-day filter (Tất cả / Hôm nay / Hôm qua /
    Chọn ngày) — the consult's call-disposition chips (Đã trả lời / Nhỡ / Để
    lại lời nhắn) and 7/30-day ranges have no backing (no disposition field in
    `cloudfone_call_transcripts`; the day filter is one exact day). Card badge
    shows the real per-call state "đã lưu"; the "tên" slot carries `caller`
    (the model's single identity field), with the transcript preview in the
    gray-600 subtitle slot. Per-utterance timestamps are omitted: the stored
    transcript is `S<n>: text` lines only (`speech_to_text.py`
    `_render_transcript` drops the ASR segment times) — adding them needs a
    backend render change (out of scope, `feat(fe)`).
  - "Hiển thị & Thông báo" holds the two notification sends that exist
    (candidate digest mail, daily Cloudfone report); the product has no
    theme/language settings to put there.
  - Dev-DB evidence plumbing (not app code): the shared dev DB sat on an
    orphaned alembic revision (`0074_ten_du_an_project`, foreign lineage) —
    repaired to `0073_map_lgd_messenger_ad`, upgraded 0074–0077, and seeded
    3 transcripts + 2 inspected-day markers via
    `plans/qa-261021/settings-mobile-seed.sql` (idempotent, ON CONFLICT DO
    NOTHING).
  - Scrim-tap dismissal is asserted in the real-browser evidence log, not in
    vitest: the browser test lane's synthetic pointer events do not reach
    React Aria's interact-outside handler (Escape path is unit-tested).
