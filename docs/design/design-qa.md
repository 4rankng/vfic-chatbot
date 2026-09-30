# Design QA

## Prior performance-dashboard validation

Selected design direction: diagnostic matrix (Image Gen option 2), based on the
existing `/hieu-suat` screen and the light Ting Ting workspace system.

- Typecheck, lint, and production build passed.
- The authenticated local route rendered successfully with an admin session.
- Window control, refresh, empty states, populated telemetry, and the prior
  390 × 844 mobile presentation were verified.

The local seed includes healthy, warning, and failure telemetry for future
performance-page reviews.

## Current mobile-native redesign

- Source visual truth: `/Users/dev/.codex/generated_images/019f57ad-4c82-7a10-856f-d646d4421c44/exec-3a547db6-993a-4b3b-a041-861fa8ee3232.png` (selected option 2).
- Intended viewport set: iPhone 15 Pro, iPhone SE, Pixel 8, and Galaxy S23.
- Intended states: dashboard empty and candidate-row states; project selection and actions; Zalo credential disclosure and connection test; performance metric rail and diagnostic disclosures; bottom-navigation active and overflow states.

## Evidence gap

Chrome’s automation connection returned `Browser is not available: extension` before any live page could be opened. Consequently, no browser-rendered implementation screenshot, device capture, interaction test, console check, or visual comparison can be produced in this session.

## Static validation completed

- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `npm run test:unit:app` — 29 files / 219 tests passed.
- `npm run build` — passed.

## Required browser verification after Chrome is connected

1. Capture every affected route before/after at the four target viewports.
2. Verify dashboard candidate navigation and empty-state density.
3. Verify project selection, edit menu, create/upload actions, and quick-stat truncation.
4. Verify settings disclosures, masked-field reveal/copy controls, clipboard behavior, and inline tests.
5. Verify metric carousel scrolling, window selection, slow-turn details, and one-at-a-time diagnostic disclosures.
6. Verify fixed navigation, safe-area spacing, overflow sheet, keyboard focus, and no horizontal overflow.

Archived prior result: blocked

---

## Current conversation-header density correction

- Source visual truth: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/codex-clipboard-a07b6bd1-3d66-4fe3-9951-dfadd4dcb610.png` (user-provided excess-space capture) plus Tailkit `a-c-chat-09` as the compact card-header reference.
- Browser-rendered implementation: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/tingting-header-compact-mobile.png`.
- Focused side-by-side comparison: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/tingting-header-compact-comparison.png`.
- Viewports: 390 × 844 mobile detail and 768 × 900 split-pane tablet.
- State: authenticated Zalo OA conversation detail with chatbot ownership, candidate context action, and transcript scrolled to the latest messages.

### Full-view comparison evidence

- Mobile: the conversation detail remains 390px wide with no horizontal overflow. The transcript and takeover footer remain visible and independently scrollable.
- Tablet: the 316px directory and 334px conversation pane remain aligned inside the workspace frame with no overflow or clipped persistent controls.

### Focused header comparison evidence

- Before: candidate name wrapped, the raw provider ID split across multiple lines, and four actions competed with identity in one row.
- After: the candidate name stays on one line; the chat-mode icon remains a dedicated control; every secondary action moves into one three-dot menu in the same 62px header row.

### Required fidelity surfaces

- Fonts and typography: Be Vietnam Pro is preserved; the contact name is readable at its existing weight without wrapping or forced character-level breaks.
- Spacing and layout rhythm: the narrow header returns to one 62px row with a 208px identity slot and a compact 94px action area.
- Colors and visual tokens: the existing Tailkit/Vantai white, zinc, hairline, and emerald action tokens are unchanged.
- Image quality and assets: existing source avatars and Lucide/product icons are preserved; no placeholder or replacement asset was introduced.
- Copy and content: Vietnamese labels and ARIA names are unchanged; only the low-value raw provider ID is hidden in the constrained header while remaining available on wider panes.

### Comparison history

1. P1 — cramped narrow-pane identity header. The first user capture showed multiline name/ID wrapping and controls crowding the contact identity.
2. Fix — the first iteration used two rows, removing crowding but introducing excessive vertical space.
3. P2 — excess action-row whitespace. The second user capture showed the header consuming too much vertical space.
4. Fix — preserved chat mode as a standalone icon and consolidated Agent Thinking, candidate information, and delete into one three-dot menu.
5. Post-fix evidence — mobile header is 378 × 62px; the identity slot is 208px, the action area is 94px, and there is no horizontal overflow.

### Interaction and console checks

- Authenticated navigation and Zalo OA conversation selection rendered successfully.
- List/detail responsive transition and persistent transcript/footer layout were exercised.
- The three-dot menu was opened and verified to contain Agent Thinking, candidate information, and delete.
- Agent Thinking opened its sheet, and candidate information opened its context dialog from the consolidated menu.
- No new console error was emitted during the corrected-header capture.

### Findings

- No remaining P0/P1/P2 mismatch in the corrected narrow header.

final result: passed

---

## Tailkit full-frontend redesign

Design direction: a restrained recruiting control room using the existing
console-blue shell, cool cloud canvas, Be Vietnam Pro type, emerald action
accent, flat bordered surfaces, and Tailkit's alternate-card hierarchy.

### Tailkit source patterns used

- Page hierarchy and nested navigation: `a-l-dark-sidebar-06`,
  `a-c-navigation-09`, `a-c-page-headings-03`, and
  `a-c-page-headings-04`.
- Resource lists and audit screens: `a-c-tables-14`, `a-c-tables-15`,
  `a-c-list-groups-05`, `a-c-badges-04`, and `a-c-empty-states-03`.
- CRUD and settings forms: `a-c-form-layouts-04`,
  `a-c-form-layouts-05`, `a-c-form-elements-02`,
  `a-c-form-switches-07`, and `a-c-form-actions-05`.
- Authentication and conversation surfaces: `a-p-sign-in-06`,
  `a-p-password-reset-06`, `a-c-chat-09`, `a-c-dropdowns-02`, and
  `a-c-offcanvas-02`.

### Production adoption

- A shared Tailkit production layer now reaches every authenticated route via
  `WorkspaceFrame`, normalizing cards, form controls, tables, focus, mobile
  touch targets, and reduced motion without changing route behavior.
- Knowledge-base list/create/show, user list/create/edit, and bot-run list/show
  now use the shared responsive page heading, page canvas, alternate-card,
  list, form, and empty-state primitives.
- Dashboard and performance headers/panels use the same hairline hierarchy and
  muted surface roles as the resource pages.
- Existing mature project, knowledge-source, persona, settings, profile, auth,
  and conversation workspaces retain their specialized behavior while sharing
  the global Tailkit token and interaction layer.

### Browser evidence

- Authenticated canonical routes checked: dashboard, conversations, project
  list/create, knowledge-source list, knowledge-base list/create, persona list,
  settings, profile, user list/create, bot-run list, and performance.
- Public/edge routes checked: login, password recovery, and not-found.
- Settings sections checked on desktop and mobile: Zalo, Messenger, Minimax,
  OpenRouter, Agents, and Users.
- Responsive widths checked: 375, 390, 768, 1024, and 1440 pixels. Across 70
  authenticated route renders plus 15 public/edge renders, document overflow
  was zero.
- Mobile interactive controls were measured after the final CSS cascade; the
  minimum visible button/control target was 44px.
- Mobile conversation detail measured 390px document width with a 378×62px
  header, separate 44px chat-mode control, separate 44px three-dot control,
  hidden provider ID, and no bottom-navigation collision.
- The three-dot menu was opened and verified to contain Agent Thinking,
  candidate information, and delete.
- Closing the externally controlled Agent Thinking sheet returns keyboard
  focus to the three-dot conversation-action trigger.

### Automated verification

- `npm run lint` — passed.
- `npm run typecheck` — passed.
- Focused Tailkit primitive tests — 4 files / 23 tests passed.
- `npm run test:unit:app` — 72 files / 423 tests passed.
- `npm run build` — passed (3,198 modules transformed).
- `git diff --check` — passed.

final result: passed

---

## Project category current-data editor

- Tailkit sources: `a-c-list-groups-03`, `a-c-list-groups-04`,
  `a-c-card-headings-03`, `a-c-empty-states-03`, and
  `a-c-form-actions-03`.
- Selecting a category now loads and labels the source currently used by the
  Agent; template YAML is never inserted into the editor as missing-data
  fallback.
- A category without an active source shows an empty editor and a clear
  `Chưa có dữ liệu` state. Its template remains available only through the
  independent `Tải mẫu` action.
- Current YAML is read-only. Replacement is intentionally available only
  through `Tải file YAML`; the redundant manual-replace and category-delete
  footer actions were removed.
- Late responses from a previously selected category are ignored, preventing
  stale content from replacing the category the user is currently viewing.
- Authenticated browser QA verified LG-DISPLAY `Vị trí tuyển dụng` v2 and
  `Lương & thu nhập` v1 against their distinct current source filenames and
  contents, with no console errors.

---

## Messenger settings density and contrast

- Tailkit sources: `a-c-form-layouts-03`, `a-c-form-elements-10`,
  `a-c-form-elements-16`, `a-c-card-headings-02`,
  `a-c-form-actions-03`, and `a-c-alerts-01`.
- Removed the repeated Facebook Messenger heading and long setup explanation;
  credentials now use a compact two-column desktop grid and one-column mobile
  grid with short field guidance.
- Primary actions use an explicit solid surface/foreground pair. Disabled
  actions retain readable slate text on a muted surface with opacity 1 and a
  `not-allowed` cursor.
- Browser QA measured zero horizontal overflow at 390px and 1440px. Mobile
  buttons are 44px high; enabled and disabled foreground/background colors are
  distinct, and no console errors were emitted.

---

## Untitled UI adoption and console-density pass

The console was rebuilt on Untitled UI PRO primitives while keeping the existing
brand: ink topbar and rail, warm canvas, the three-pane conversation workspace,
the current information density, and every Vietnamese string. Untitled UI
supplied structure and components, never a new visual identity.

### What changed

- **Shell.** Full-width ink topbar (brand tile left; notifications and account
  menu right) over a 72px icon-first rail with tooltips, a slate active marker,
  and a React Aria `SlideoutMenu` drawer below `lg`. `.workspace-frame` /
  `.workspace-frame-content` remain the token and scroll roots.
- **Palette.** The brick-red accent is replaced by a professional slate ramp
  across the daisyUI theme, the shadcn slots, `.kb-scope`, the login paper and
  the `--color-uu-brand-*` ramp. Contrast was corrected arithmetically until
  every pair cleared WCAG AA: `--primary #557498`, ring `#7796b6`,
  warning `#8c6621`, info `#466fa0`, error `#ad5d68`, success `#0b7e56`, plus
  dark-mode and on-brand ink corrections.
- **Token layer.** The retired Tailkit layer's load-bearing geometry moved onto
  the daisyUI theme tokens. `src/index.css` now owns the console palette and
  `src/styles/untitledui-theme.css` the library vocabulary, with the four
  colliding utility names (`bg-primary`, `bg-secondary`, `text-primary`,
  `border-primary`) pinned to the console on `:root` and re-bound inside
  `.uu-scope`. `untitledui-theme-contract.test.ts` guards that split.
- **Kit.** `PageShell`, `PageHeading`, `EmptyState`, `kit/form-controls.tsx` and
  `kit/list-table.tsx` carry the shared page furniture; dashboard, settings,
  users, knowledge base, automation, knowledge, personas, conversations, auth,
  profile, performance and projects were migrated onto them in place.

### Inbox directory header and channel indicator

Two defects the owner flagged, both fixed and verified in a real browser:

- **The header reserved space it did not use.** `.workspace-rail` declared a
  two-row grid (`"title adapters" / "search search"`) but only `title` and
  `adapters` were assigned, so the search row had no `grid-area` and the field
  collapsed to **119×42px** inside a 323px rail, leaving a void beneath it. The
  tools row is now assigned to `grid-area: search`, the reserved
  `min-height: 194px` is gone, and the rail's padding and gap are tightened.
  Measured in the browser at 1440×900: the rail header is now **≤130px** tall
  (from 194px) and the search field fills the rail width (>200px). Every header
  control is **≤40px** — channel tiles 44→40, search field 42 (46 on mobile)→40.
- **A thread's origin was invisible in the list.** Each row now carries an 18px
  channel chip keyed off `channel_identity.provider`, using a short Vietnamese
  row label (`Chatbot`, `Zalo OA`, `Messenger`, `TingTing`) added beside the
  full-label map in `atomic-crm/types.ts`; the full name — including
  `Zalo OA TingTing (hỗ trợ nhân viên)` — stays on the element's `title`, and
  notifications and panels keep the full labels. Unknown or absent providers
  fall back to `Kênh khác`, and the chip is tinted per channel.

The chip is scoped by its own class prefix rather than as a descendant of the
shared `.inbox-bg-container`, so the FE-19 scoping ratchet is untouched
(`MAX_UNSCOPED_RULES` stays at 570).

### Browser evidence

- Desktop 1440×900 and phone 390×844, authenticated: rail header compact, search
  field full width, four channel tiles, and the `Zalo OA` chip on the seeded
  candidate row. No horizontal overflow at either width.
- Focused unit run covering the change: `src/components/atomic-crm/conversations`
  plus `css-scoping.test.ts` — 23 files / 133 tests passed.

final result: passed for the surfaces above

### Open at the time of writing

- The full-suite, lint and build gates were re-run while another session held
  `src/components/atomic-crm/projects/domain/project-knowledge-yaml.ts`
  truncated mid-edit (44 lines, unterminated regex at line 45). That file breaks
  the vite/oxc dependency scan, so `npm run test:unit:app`, `npm run build` and
  `npm run lint` fail on it rather than on anything in this pass. Re-run the
  three once that file is whole; the focused suites and the browser evidence
  above are unaffected.
