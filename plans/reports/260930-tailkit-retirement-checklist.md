# Tailkit retirement checklist — 2026-09-30

Evidence snapshot from the read-only inventory of `frontend/src` + `frontend/scripts`.
Paths relative to `frontend/`. **`tt-*` is daisyUI's class prefix** — set at
`src/index.css:115-123` (`@plugin "daisyui" { … prefix: "tt-" }`, include list:
alert, avatar, badge, breadcrumbs, button, card, chat, checkbox, collapse, hero,
input, join, loading, menu, modal, navbar, radio, select, skeleton, tab, table,
textarea, toggle). A `tt-*` class call site therefore retires **only when its
markup is replaced** (or the prefix/include entry is dropped) — there is no repo
CSS to delete for these classes. `.tt-btn-touch`, `.tt-page-shell`,
`.tt-alternate-card` have no definition anywhere in `frontend/src`
(marker/query-only). Caveat: sibling agents converted `var(--tt-*)` usages in
`automation/BotRunList.tsx`, `automation/BotRunShow.tsx`,
`knowledge-base/KnowledgeBaseCreate.tsx`, `knowledge-base/KnowledgeBaseList.tsx`
during the scan — those are already done; everything below is the remaining set.

---

## 1. `--tt-*` → console token mapping (execute first)

Declarations: `conversations/inbox/tokens.css:167-218` (light) and `:318-341`
(dark); `kit/tailkit-system.css:14-25` (`.workspace-frame` re-alias). Replace each
token name at its consumers with the console token in column 2, then delete the
declarations (step 4 of §4).

| `--tt-*` token | becomes | current consumers (file:line) |
|---|---|---|
| `--tt-sidebar` | `--workspace-shell` | none (decl only: tokens.css:167, :318) |
| `--tt-sidebar-hover` | `--workspace-shell-hover` | none (tokens.css:168, :319) |
| `--tt-sidebar-active` | `--workspace-shell-rail-active` | none (tokens.css:169, :320) |
| `--tt-sidebar-border` | `--workspace-border` (hairline role) | none (tokens.css:170, :321) |
| `--tt-sidebar-ink` | `--workspace-ink` (light-on-slate literal `#f1f5f9`) | none (tokens.css:171, :322) |
| `--tt-sidebar-ink-muted` | `--workspace-ink-muted` | none (tokens.css:172, :323) |
| `--tt-sidebar-accent` | `--workspace-teal` | none (tokens.css:173, :324) |
| `--tt-sidebar-accent-soft` | `--workspace-teal-soft` | none (tokens.css:174, :325-328 dark) |
| `--tt-canvas` | `--workspace-canvas` | kit/tailkit-system.css:29 |
| `--tt-surface` | `--workspace-surface` | none (tokens.css:177) |
| `--tt-surface-muted` | `--workspace-surface-muted` | kit/tailkit-system.css:52, :74; inbox/untitledui-conversations.css:475; users/account-layout-regressions.test.tsx:51 (fixture) |
| `--tt-surface-lift` | `--card` (shadcn elevated surface) | personas/PersonaList.tsx:226; personas/persona-layout-regressions.test.tsx:83; users/account-layout-regressions.test.tsx:51 (fixture) |
| `--tt-surface-hover` | `--workspace-hover` | none (tokens.css:180, :332) |
| `--tt-ink` | `--workspace-ink` | kit/tailkit-system.css:30; inbox/untitledui-conversations.css:476; users/users.css:32, :102; users/account-layout-regressions.test.tsx:49 (fixture) |
| `--tt-ink-muted` | `--workspace-ink-muted` | kit/tailkit-system.css:53, :75; inbox/untitledui-conversations.css:499; personas/PersonaList.tsx:182, :240; personas/persona-layout-regressions.test.tsx:59; users/users.css:47, :110; users/account-layout-regressions.test.tsx:50 (fixture) |
| `--tt-ink-faint` | `--workspace-faint` | none (tokens.css:184) |
| `--tt-border` | `--workspace-border` | inbox/tokens.css:214, :341 (inside `--tt-ring-inset`); kit/tailkit-system.css:34, :39, :44, :57, :73; knowledge-base/KnowledgeBaseShow.tsx:38, :62, :78, :256, :289, :316, :331, :421; personas/PersonaList.tsx:226; personas/persona-layout-regressions.test.tsx:83; users/users.css:66, :77, :94, :140, :151; users/account-layout-regressions.test.tsx:48 (fixture) |
| `--tt-border-strong` | `--border-strong` (tokens.css:13) | none (tokens.css:187, :339) |
| `--tt-ring` | `--workspace-focus` | none (tokens.css:188, :337) |
| `--tt-accent` | `--workspace-action` | inbox/untitledui-conversations.css:482; conversations/presentation/ChatMessageRow.test.tsx:53 (test probe) |
| `--tt-accent-strong` | `--workspace-action-strong` | users/users.css:94, :97; users/account-layout-regressions.test.tsx:53 (fixture) |
| `--tt-accent-soft` | `--workspace-teal-soft` | kit/tailkit-system.css:61; users/users.css:96; users/account-layout-regressions.test.tsx:52 (fixture) |
| `--tt-success` | `--workspace-success` | none (tokens.css:193) |
| `--tt-warning` | `--workspace-warning` | none (tokens.css:194) |
| `--tt-danger` | `--workspace-danger` | none (tokens.css:195) |
| `--tt-gap-page` | `--workspace-space-6` | none (tokens.css:200) |
| `--tt-gap-section` | `--workspace-space-6` | none (tokens.css:201) |
| `--tt-gap-card` | `--workspace-space-4` | none (tokens.css:202) |
| `--tt-gap-row` | `--workspace-space-2` | none (tokens.css:203) |
| `--tt-pad-card` | `--workspace-space-4` | none (tokens.css:204) |
| `--tt-pad-page` | `--workspace-space-6` | none (tokens.css:205) |
| `--tt-radius` | `--workspace-radius-panel` | none (tokens.css:208) |
| `--tt-radius-control` | `--workspace-radius-control` | none (tokens.css:209) |
| `--tt-radius-pill` | `rounded-full` (9999px) | none (tokens.css:210) |
| `--tt-shadow-xs` | `--workspace-shadow-panel` | none (tokens.css:211, :340) |
| `--tt-shadow-sm` | `--shadow-sm` (tokens.css:22) | none (tokens.css:212) |
| `--tt-shadow-md` | `--shadow-md` (tokens.css:25) | none (tokens.css:213) |
| `--tt-ring-inset` | `ring-1 ring-inset` over `--workspace-border` | none (tokens.css:214, :341) |
| `--tt-motion-fast` | `--workspace-motion-fast` | none (tokens.css:217) |
| `--tt-motion-standard` | `--workspace-motion-standard` | none (tokens.css:218) |
| `--tt-size` (local sizing var) | `height`/`min-height` literal (2rem / 1.75rem / 2.25rem) | kit/tailkit-system.css:84 set, :87, :88 read; :97 set, :100, :101 read; :110 set, :113, :114 read |
| `--tt-btn-p` (local sizing var) | `padding-inline` literal (0.75rem / 0.625rem / 1rem) | kit/tailkit-system.css:85, :98, :111 (set; no read observed) |
| `--tt-fontsize` (local sizing var) | delete — dead declaration | kit/tailkit-system.css:86, :99, :112 (set; `font-size` reads `--fs-body-sm` directly at :89, :102, :115) |

Dark-theme overrides to re-point at the same targets: tokens.css:318-341
(`--tt-sidebar` :318, `-hover` :319, `-active` :320, `-border` :321, `-ink` :322,
`-ink-muted` :323, `-accent` :324, `-accent-soft` :325-328, `--tt-surface-lift`
:331, `--tt-surface-hover` :332, `--tt-accent` :333, `--tt-accent-strong` :334,
`--tt-accent-soft` :335, `--tt-ring` :337, `--tt-border` :338, `--tt-border-strong`
:339, `--tt-shadow-xs` :340, `--tt-ring-inset` :341).

Also migrate the test fixture `users/account-layout-regressions.test.tsx:48-53`
(keys `--tt-border`, `--tt-ink`, `--tt-ink-muted`, `--tt-surface-lift`,
`--tt-accent-soft`, `--tt-accent-strong`) and the colour probes
`conversations/presentation/ChatMessageRow.test.tsx:51, :53` in the same pass.

---

## 2. `tt-*` class call sites by owning screen (execute second)

Reminder: `tt-*` is **daisyUI's prefix**, not repo CSS (src/index.css:115-123).
Each call site below retires only when the markup is replaced with
console/Untitled UI equivalents — no stylesheet edit makes these classes go away.
`applied` = class string in JSX; `test+` = positive assertion; `test-` = negative
assertion (class must stay ABSENT).

### Shadcn primitives — components/ui (affects every screen)
- components/ui/alert.tsx:7 `tt-alert`; :12 `tt-alert-info tt-alert-soft`; :13 `tt-alert-warning tt-alert-soft`; :14 `tt-alert-error tt-alert-soft` — applied
- components/ui/alert.test.tsx:20 `tt-alert-info`; :21 `tt-alert-soft` — test+
- components/ui/avatar.tsx:15 `tt-avatar`; :45 `tt-avatar-placeholder` — applied
- components/ui/badge.tsx:8 `tt-badge`; :12 `tt-badge-primary`; :13 `tt-badge-secondary tt-badge-soft`; :15 `tt-badge-error`; :17 `tt-badge-outline` — applied
- components/ui/breadcrumb.tsx:12 `tt-breadcrumbs` — applied
- components/ui/button.tsx:8 `tt-btn`; :12 `tt-btn-primary`; :13 `tt-btn-error`; :16 `tt-btn-outline`; :17 `tt-btn-secondary tt-btn-soft`; :19 `tt-btn-ghost`; :20 `tt-btn-link`; :25 `tt-btn-md`; :26 `tt-btn-sm`; :27 `tt-btn-lg`; :28 `tt-btn-touch tt-btn-lg`; :29 `tt-btn-square`; :30 `tt-btn-square tt-btn-sm`; :31 `tt-btn-touch tt-btn-square tt-btn-lg` — applied
- components/ui/card.tsx:10 `tt-card tt-card-border` — applied
- components/ui/checkbox.tsx:14 `tt-checkbox tt-checkbox-primary tt-checkbox-sm` — applied
- components/ui/dialog.tsx:66 `tt-modal-box` — applied (comment :58 explains the open-state override)
- components/ui/input.tsx:11 `tt-input` — applied
- components/ui/pagination.tsx:30 `tt-join`; :61 `tt-join-item` — applied
- components/ui/radio-group.tsx:27 `tt-radio tt-radio-primary tt-radio-sm` — applied
- components/ui/select.tsx:38 `tt-select` — applied
- components/ui/skeleton.tsx:12 `tt-skeleton` — applied
- components/ui/spinner.tsx:18 `tt-loading tt-loading-spinner`; :21 `tt-loading-sm`; :22 `tt-loading-md`; :23 `tt-loading-lg` — applied
- components/ui/switch.tsx:21 `tt-toggle tt-toggle-primary tt-toggle-md` — applied
- components/ui/table.tsx:14 `tt-table tt-table-sm` — applied
- components/ui/tabs.tsx:27 `tt-tabs tt-tabs-border`; :43 `tt-tab` — applied
- components/ui/textarea.tsx:10 `tt-textarea` — applied
- components/ui/daisy-adapters.test.tsx:56 `tt-btn-primary`; :82 `tt-btn-touch`; :85 `tt-btn-outline`; :88 `tt-input`; :91 `tt-textarea`; :92 `tt-badge`; :93 `tt-alert`; :94 `tt-card`; :95 `tt-skeleton`; :96 `tt-loading-spinner`; :97 `tt-table`; :121 `tt-checkbox`; :122 `tt-toggle`; :126 `tt-radio`; :129 `tt-select`; :213 `tt-join`; :214 `tt-join-item`; :215 `tt-tabs`; :216 `tt-tab`; :220 `tt-modal-box` — test+

### shadcn-admin-kit framework — components/admin (all react-admin forms)
- components/admin/file-input.tsx:234 `tt-card tt-card-dash` — applied
- components/admin/form.tsx:248 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- components/admin/spinner.tsx:17 `tt-loading tt-loading-spinner`; :20 `tt-loading-sm`; :21 `tt-loading-md`; :22 `tt-loading-lg` — applied

### Global app shell (bootstrap error + loading)
- src/App.tsx:63 `tt-card tt-card-border`; :88 `tt-alert`; :92 `tt-loading tt-loading-spinner tt-loading-sm` — applied

### bot_runs screen (automation)
- atomic-crm/automation/DecisionTracePanel.tsx:55 `tt-alert`; :162 `tt-alert tt-alert-warning tt-alert-soft`; :221, :362 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/automation/BotRunPages.test.tsx:60 `.tt-page-shell` query (polarity unverified); :79, :146 `.tt-alternate-card` — test-

### conversations inbox screen
- atomic-crm/conversations/ConversationContextPanel.tsx:343, :363 `tt-card tt-card-sm`; :348 `tt-badge tt-badge-soft` — applied
- atomic-crm/conversations/presentation/ChatMessageRow.tsx:143 `tt-chat-bubble`; :198 `tt-chat` / `tt-chat-start` / `tt-chat-end` — applied
- atomic-crm/conversations/presentation/ChatThread.tsx:486 `tt-alert tt-alert-warning tt-alert-soft`; :492, :508, :566 `tt-btn tt-btn-sm tt-btn-outline`; :501 `tt-alert tt-alert-error tt-alert-soft`; :537 `tt-btn tt-btn-sm` + `tt-btn-primary`; :557 `tt-alert tt-alert-info tt-alert-soft`; :580 `tt-textarea`; :595 `tt-btn tt-btn-primary tt-btn-circle` — applied
- atomic-crm/conversations/presentation/ConversationList.tsx:261 `tt-skeleton`; :313 `tt-btn tt-btn-sm tt-btn-outline`; :339 `tt-card tt-card-sm`; :341 `tt-badge tt-badge-soft`; :350 `tt-card-body`; :351 `tt-card-title`; :552 `tt-input` — applied
- atomic-crm/conversations/presentation/ConversationShow.tsx:283 `tt-btn tt-btn-sm` — applied

### settings / channel-integrations screen (integrations)
- atomic-crm/integrations/FacebookMessengerIntegrationPage.tsx:417, :447, :457, :511, :579, :651 `tt-btn-touch`; :537 `tt-radio tt-radio-primary tt-radio-sm` — applied
- atomic-crm/integrations/FacebookMessengerPageCard.tsx:221 `tt-btn-touch` — applied
- atomic-crm/integrations/JevSection.tsx:101, :124 `tt-btn-touch` — applied
- atomic-crm/integrations/LlmProvidersSection.tsx:180, :274, :283 `tt-btn-touch` — applied
- atomic-crm/integrations/SettingsGroup.tsx:50 `tt-collapse tt-collapse-arrow`; :54 `tt-collapse-title`; :57 `tt-collapse-content` — applied
- atomic-crm/integrations/TingtingSection.tsx:295, :310 `tt-btn-touch` — applied
- atomic-crm/integrations/ZaloChannelSection.tsx:112, :186 `tt-btn-touch` — applied
- atomic-crm/integrations/settings-workspace-layout.test.tsx:181 `.tt-card` query — test-; :182 `tt-card` — test-

### knowledge_sources screen (knowledge)
- atomic-crm/knowledge/InlineKnowledgeUploader.tsx:131 `tt-card tt-card-dash`; :168 `tt-alert tt-alert-error tt-alert-soft` — applied
- atomic-crm/knowledge/KnowledgeDetailPanel.tsx:124, :139, :163, :178 `tt-btn-touch` — applied
- atomic-crm/knowledge/KnowledgeSourceEdit.tsx:80, :131, :139 `tt-btn-touch` — applied
- atomic-crm/knowledge/KnowledgeSourceList.tsx:75, :180, :238 `tt-btn-touch` — applied
- atomic-crm/knowledge/KnowledgeSourceShow.tsx:31 `tt-btn-touch` — applied
- atomic-crm/knowledge/KnowledgeUpload.tsx:209, :331 `tt-alert tt-alert-info tt-alert-soft`; :241 `tt-card tt-card-dash`; :321 `tt-alert tt-alert-error tt-alert-soft` — applied
- atomic-crm/knowledge/KnowledgeVersionManager.tsx:70 `tt-btn-touch` — applied
- atomic-crm/knowledge/ProjectPicker.tsx:149 `tt-btn-touch` — applied
- atomic-crm/knowledge/StoredKnowledgePanel.tsx:141, :154 `tt-btn-touch` — applied

### knowledge_bases screen (knowledge-base)
- atomic-crm/knowledge-base/KnowledgeBasePages.test.tsx:111, :143 `.tt-alternate-card` — test-
- atomic-crm/knowledge-base/KnowledgeBaseShow.test.tsx:187 `.tt-alternate-card` — test-

### login / auth screens
- atomic-crm/login/AuthShell.tsx:11 `tt-hero`; :14 `tt-card tt-card-border`; :28, :34 `tt-badge tt-badge-primary tt-badge-soft` — applied
- atomic-crm/login/AuthShell.test.tsx:24 `main.tt-hero` — test+
- atomic-crm/login/ForgotPasswordPage.tsx:110 `tt-card`; :128, :175, :191 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/login/LoginPage.tsx:46 `tt-card tt-card-border`; :65 `tt-loading tt-loading-spinner tt-loading-sm` — applied

### profile screen (settings)
- atomic-crm/settings/ProfilePage.tsx:178, :186, :207, :233 `tt-btn-touch` — applied

### performance / reporting screen
- atomic-crm/performance/presentation/pageStates.tsx:23 `tt-alert` — applied
- atomic-crm/performance/presentation/adapterComparison/AdapterComparison.tsx:35 `tt-table tt-table-sm` — applied
- atomic-crm/performance/presentation/slowestTurns/SlowestTurns.tsx:30 `tt-card tt-card-border`; :53 `tt-table tt-table-sm` — applied
- atomic-crm/performance/presentation/stageMatrix/StageMatrix.tsx:82 `tt-table tt-table-sm` — applied
- atomic-crm/performance/PerformancePage.test.tsx:166 `.tt-card` query — test-
- atomic-crm/performance/performance-trend-layers.test.tsx:375 `tt-card tt-card-border` — test fixture

### personas screen
- atomic-crm/personas/PersonaAssignments.tsx:206, :258, :311, :332 `tt-btn-touch`; :213, :321, :347 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/personas/PersonaEdit.tsx:147, :157 `tt-btn-touch` — applied
- atomic-crm/personas/PersonaForm.tsx:356, :365, :591 `tt-btn-touch`; :372, :598 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/personas/PersonaList.tsx:50 `tt-list-row`; :190 `tt-btn-touch`; :198 `tt-input`; :227 `tt-list` — applied
- atomic-crm/personas/presentation/PersonaStudioOverview.tsx:162 `tt-btn-touch`; :209 `tt-progress tt-progress-success` — applied
- atomic-crm/personas/persona-layout-regressions.test.tsx:66, :106, :479 `tt-btn-touch`; :74 `tt-input`; :85 `tt-list-row` — test fixture; :139, :140 `tt-card` — test-

### projects screen
- atomic-crm/projects/ProjectBusTimetable.tsx:75 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/projects/ProjectKnowledgePanel.tsx:158 `tt-btn-touch`; :165, :354 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/projects/ProjectList.tsx:224 `tt-badge-success tt-badge-soft` — applied
- atomic-crm/projects/ProjectShow.tsx:39 `tt-badge-success tt-badge-soft` — applied
- atomic-crm/projects/presentation/CategoryEditor.tsx:105, :118, :127, :148 `tt-btn-touch`; :135 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/projects/presentation/DiscoveryCardEditor.tsx:57 `tt-loading tt-loading-spinner tt-loading-sm` — applied
- atomic-crm/projects/presentation/SinglePageEditor.tsx:112 `tt-loading tt-loading-spinner tt-loading-sm` — applied

### users screen
- atomic-crm/users/account-layout-regressions.test.tsx:127, :128 `tt-card` — test-

### e2e (inbox journey)
- e2e/vfic.spec.ts:37 `.conversation.tt-btn` query — test- (`shrunkRows` expects null)

### CSS selector references to `.tt-*` (only kit/tailkit-system.css; see §3)
- kit/tailkit-system.css:71 `.tt-btn-primary:disabled`; :72 `.tt-btn-error:disabled`; :81-83 `.tt-btn` with exclusions; :94-95 `.tt-btn.tt-btn-sm`; :107-109 `.tt-btn.tt-btn-lg`; :128 `.tt-page-heading-row`; :132 `.tt-page-heading-actions`

Negative pins that must keep passing after retirement (class must remain absent):
BotRunPages.test.tsx:79/:146, KnowledgeBasePages.test.tsx:111/:143,
KnowledgeBaseShow.test.tsx:187, settings-workspace-layout.test.tsx:181/:182,
PerformancePage.test.tsx:166, persona-layout-regressions.test.tsx:139/:140,
account-layout-regressions.test.tsx:127/:128, e2e/vfic.spec.ts:37.

---

## 3. Load-bearing rules in kit/tailkit-system.css → where they must live afterwards

Control geometry must not change when the file is deleted. Move each rule to its
new home and verify rendered heights before deleting.

| rule (file:line) | what it pins | must live afterwards in |
|---|---|---|
| :79-118 (desktop ≥768px) | text actions 28/32/36px: `height`+`min-height` `!important` from `--tt-size` 1.75/2/2.25rem (set :84, :97, :110; read :87-88, :100-101, :113-114), label `font-size: var(--fs-body-sm)` (13px) + `font-weight: var(--fw-semibold)` (600) at :89-90, :102-103, :115-116; padding via `--tt-btn-p` :85, :98, :111 | components/ui/button.tsx size variants — `sm` :26 (`h-7` = 28px), `default` :25 (`h-8` = 32px), `lg` :27 (`h-9` = 36px) already carry the heights; add matching `min-h-*`, `text-[length:var(--fs-body-sm)]`, `font-semibold` there so geometry survives without `!important`. Keep the exclusion semantics: `touch` :28/:31 stays `h-11`, `icon`/`icon-sm` :29/:30 stay square (`tt-btn-square`), `.conversation` rows keep their own height (pinned by kit/tailkit-action-sizing.test.tsx:139 and e2e/vfic.spec.ts:37) |
| :120-126 (max-width 767px) | every `button`, `a[role=button]`, `input:not(checkbox/radio)`, `select` inside the shell gets `min-height: 44px !important` (WCAG touch target) | components/ui/button.tsx (mobile floor already `max-md:h-11` at :25-28, :30-31), components/ui/input.tsx:11, components/ui/select.tsx:38, components/ui/textarea.tsx:10 need the equivalent `max-md:min-h-11`; raw non-ui `<button>` call sites (e.g. ChatThread.tsx:595, ConversationList.tsx:313) need per-feature equivalents in their scoped sheets |
| :71-76 | disabled solid actions: `border-color: var(--tt-border)`, `background: var(--tt-surface-muted)`, `color: var(--tt-ink-muted)`, `opacity: 1` for `.tt-btn-primary:disabled` and `.tt-btn-error:disabled` (comment :68-70: white-on-brand disabled text went illegible) | components/ui/button.tsx variant `default` (:12 `tt-btn-primary`) and `destructive` (:13 `tt-btn-error`) disabled state — swap to `disabled:` utilities over `--workspace-border` / `--workspace-surface-muted` / `--workspace-ink-muted` so the fill neutralises at full opacity |
| :28-61 (`.tailkit-workspace-content` chrome) | `[data-slot=card]` border-color + 12px radius (:33-36), `[data-slot=card-header]` border (:38-40), input/textarea/select border (:42-45), `table` `tabular-nums` (:47-49), `thead` fill `--tt-surface-muted` + ink `--tt-ink-muted` (:51-54), `tbody tr` hairline (:56-58), `tbody tr:hover` wash `color-mix(--tt-accent-soft 45%)` (:60-62) | components/ui/card.tsx:10 (card border + radius), components/ui/input.tsx:11 / textarea.tsx:10 / select.tsx:38 (field border), components/ui/table.tsx:14 (tabular-nums, thead fill/ink, row hairline, hover wash) — or the owning feature sheets (`users/users.css`, `dashboard/dashboard.css`, …) scoped per workspace class |

Also relocating with the file (not in the four named groups but load-bearing):
:14-25 `.workspace-frame` `--tt-*` re-aliases (consumers listed in §1),
:137-144 `prefers-reduced-motion` kill-switch for the whole shell,
:128/:132 `.tt-page-heading-row`/`.tt-page-heading-actions` mobile tweaks —
these two selectors have **no emitter in frontend/src** (dead; delete outright).

---

## 4. Deletion order + preconditions (execute third→last)

Each step lists the precondition that MUST hold immediately before the deletion.

**Step 1 — `conversations/inbox/tailkit-redesign.css`.**
Precondition: the emerald inbox pass is accepted as removed or its visual intent
ported; `conversations/inbox.css:21` (`@import "./inbox/tailkit-redesign.css"`)
deleted in the same commit; `conversations/ChannelAdapterSelector.test.tsx:41-42`
comment/expectations rewritten (it pins this file's `@media (max-width: 767px)`
rules). Independent of the token chain — can land first.

**Step 2 — `kit/tailkit-action-sizing.test.tsx`.**
Precondition: the 28/32/36px + 44px geometry from §3 is re-pinned at
components/ui/button.tsx (and covered by a test at the new home), so the suite is
no longer the only guard. MUST be deleted before or in the same commit as step 3
(its `import "./tailkit-system.css"` at :6 resolves the file).

**Step 3 — `kit/tailkit-system.css`.**
Preconditions: (a) `layout/Layout.tsx:10` import removed and `.tailkit-workspace-content`
dropped from :54, plus fixture uses at
personas/PersonaList.mobile-layout.test.tsx:23 and
users/account-layout-regressions.test.tsx:90 (and its `import "../kit/tailkit-system.css"`
at :15); (b) rules scoped on `.tailkit-workspace-content` re-homed —
conversations/inbox/mobile-persona-editor.css:1143, :1157, :1270 and
integrations/settings.css:488-489, :499-504, :582-583, :590-595; (c) §3 rules
relocated and measured (28/32/36px, 44px, disabled fills, card/table chrome);
(d) `npm run registry:gen` run in the same commit (see §5).

**Step 4 — `--tt-*` blocks in `conversations/inbox/tokens.css`.**
Delete the bridge comment+declarations at :156-219 (light) and :314-341 (dark).
Precondition: after step 3, a repo-wide grep for `--tt-` returns **zero** hits —
i.e. every consumer in §1 converted: inbox/untitledui-conversations.css:475, :476,
:482, :499; conversations/presentation/ChatMessageRow.test.tsx:51, :53;
knowledge-base/KnowledgeBaseShow.tsx:38, :62, :78, :256, :289, :316, :331, :421;
personas/PersonaList.tsx:182, :226, :240; personas/persona-layout-regressions.test.tsx:59,
:83; users/users.css:32, :47, :66, :77, :94, :96, :97, :102, :110, :140, :151;
users/account-layout-regressions.test.tsx:48-53.

**Step 5 — `tailkit-contract.test.ts` + `styles/tailkit-tokens.css` (same commit).**
Preconditions: (a) step 3 done (its fallback-less `var(--color-secondary-100/50/500/200)`
reads at kit/tailkit-system.css:15, :16, :18, :20 are gone); (b) `src/index.css:4`
`@import "./styles/tailkit-tokens.css"` removed in the same commit (the contract
test asserts exactly one such import and raw-imports the file at :3-:4 — deleting
either side alone breaks resolution/assertions); (c) grep shows no
`bg-secondary-*` / `text-secondary-*` / `border-secondary-*` / `ring-secondary-*` /
`placeholder-secondary-*` utility usage left in frontend/src. `tk-card` and
`tk-focus-ring` (tailkit-tokens.css:127, :136) have zero consumers and die with
the file.

---

## 5. registry.json entries + expected regenerate/check output

Entries that publish Tailkit-only or shell files (all in `frontend/registry.json`):

| registry.json line | path | type | status |
|---|---|---|---|
| :1054 | `src/components/atomic-crm/kit/tailkit-system.css` | registry:style | Tailkit-only — must disappear after step 3 |
| :1086 | `src/components/atomic-crm/conversations/inbox/tailkit-redesign.css` | registry:style | Tailkit-only — must disappear after step 1 |
| :474 | `src/components/atomic-crm/layout/workspace-shell.tsx` | registry:component | shell file — drops only if the file is deleted |
| :634 | `src/components/atomic-crm/kit/page-shell.tsx` | registry:component | shell file — drops only if the file is deleted |

Not published (verified: grep `tailkit|tt-` over registry.json returns exactly the
two Tailkit-only rows above): `src/styles/tailkit-tokens.css` (src/styles is
outside the globs of `scripts/generate-registry.mjs`), `tailkit-contract.test.ts`,
`kit/tailkit-action-sizing.test.tsx` (tests are excluded by design). These need no
registry edit.

After the removals:
- `npm run registry:gen` diff must drop exactly the rows whose files were deleted
  (expected: :1054 and :1086; plus :474/:634 iff the shell files are deleted) and
  change nothing else — the generator is idempotent.
- `npm run registry:check` must pass: no "published file is missing", no
  "test-only", no "unpublished local dependency". Until regen runs, the check
  fails on every deleted published file.
- `frontend/.husky/pre-commit` runs `registry:gen` + prettier automatically; root
  `make release-check` runs `node scripts/check-doc-links.mjs` plus the registry
  gate — both must be green before the branch lands.
