# UI surface audit — TingHire recruiter console

- Date: 2026-09-28
- Scope: the 13 rendered surfaces of `frontend/src/components/atomic-crm/`, with
  Tailkit identifiers verified against the Tailkit MCP and Untitled UI offers
  checked against the Untitled UI MCP.
- Companion: `plans/reports/260928-ui-overhaul-part-b-completion.md` (toolchain +
  Untitled UI token layer), `plans/reports/260928-ui-overhaul-part-c-completion.md`
  (the restyle itself).

## Method, and what "verified" means here

Every Tailkit identifier named below was retrieved with
`mcp__tailkit__get_component_code` in this session — 18 identifiers across Empty
States, Tables, Statistics, Timeline, Page Headings, Form Layouts, List Groups,
Navigation and Chat. Catalog descriptions are prose; the code is what shipped.
Anatomy claims are transcribed from those responses, not paraphrased from the
catalog blurb. Identifiers that were **not** fetched are not named at all.

Untitled UI claims come from `mcp__untitledui__get_component` (component → CLI
install command) and from the library's own `theme.css` / `globals.css`, read
from the installed CLI package at `~/.npm/_npx/*/node_modules/untitledui/config/styles/`.

Surface inventory is from `capabilities/kernel/index.tsx` (routes) and
`capabilities/static-recruitment-runtime.ts` (the 8 resources), with `.tsx`
counts and `__screenshots__` baseline counts as the regression-risk proxy.

## The finding that governs everything else: Tailkit ships marketing density

Every Tailkit response retrieved this session is sized for a marketing site, not
an admin console:

| Identifier | Density it ships |
|---|---|
| `a-c-empty-states-01` | `px-6 py-20 md:py-40` frame, `text-2xl font-bold` title |
| `a-c-empty-states-03` | same frame, `size-12` icon, `flex gap-3` action row |
| `a-c-tables-08` | `px-3 py-4` cells, `py-2 pl-10` search field, `bg-secondary-100/75` thead |
| `a-c-tables-14` / `a-c-tables-15` | `rounded-xl bg-secondary-100/75 p-2` chrome, `p-4` inner card, `shadow-xs` |
| `a-c-statistics-11` | `text-2xl font-extrabold` metric, `p-5` card, inline SVG sparkline |
| `a-c-timeline-01` | `p-4` event cards, `ring-3 ring-offset-2` dots, `size-3` markers |
| `a-c-navigation-01` | `py-2` rows, `text-sm font-medium`, `rounded-lg` |
| `a-c-chat-01` | `p-3` bubbles, `rounded-2xl rounded-bl-none`, `text-sm` |
| `a-c-form-layouts-04/05` | `space-y-6` sections, `w-2/3` cards, `text-sm` labels |

The console runs 16px section titles (`--text-section-title`), 13px body
(`--text-body-sm`), `min-h-64` empty states and 14px table cells. **Density is
therefore a deliberate, per-surface deviation: Tailkit supplies anatomy, token
vocabulary and state coverage; it does not supply scale.** No Tailkit-derived
element may ship `py-20`/`md:py-40` or `text-2xl`/`text-3xl`; headings stop at
`--text-section-title`.

## Surface matrix

| Surface | Route(s) | tsx / baselines | System today | Verified Tailkit match | Untitled UI offer | Risk |
|---|---|---|---|---|---|---|
| `layout` (app shell) | every authenticated route | 5 / 1 | `WorkspaceFrame`, `--tt-*` | `a-c-navigation-01` — row anatomy: `flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium`, active row = tinted bg + border, inactive = transparent border + `hover:bg-*` | `application/*` shells **replace** the shell — not recommended | HIGH (app-wide) |
| `conversations` (Zalo inbox) | `#/conversations` | 10 / 6 | bespoke + `inbox/tokens.css` | `a-c-chat-01` — bubble anatomy: `max-w-[80%] p-3 text-sm rounded-2xl`, inbound `rounded-bl-none` on a muted surface, outbound on a solid brand fill | chat templates need their own data layer | HIGHEST |
| `integrations` (settings) | `#/settings` | 14 / 27 | daisyUI `tt-*` | `a-c-form-layouts-04/05` — `md:flex md:gap-5` section: `md:w-1/3` label+help column, `md:w-2/3` card of `space-y-6` fields | `base/select`, `base/toggle`, `base/input` | HIGH |
| `projects` | `#/projects` | 15 / 16 | — | `a-c-tables-08` — heading + count + search above a `border-secondary-200` framed table, `even:bg-secondary-50` zebra | `base/table`? (not in `base/`) — keep react-admin grid | MED-HIGH |
| `users` | `#/users` | 6 / 14 | — | `a-c-tables-08` + `a-c-form-layouts-05` | `base/select`, `base/combobox` (React Aria) | MED-HIGH |
| `performance` | `#/performance` | 12 / 5 | `PerformanceTrendChart` | `a-c-statistics-11` — metric + trend arrow + inline-SVG sparkline (`<path>` data, no chart lib) | `application/statistics` sections | MED |
| `knowledge` (sources) | `#/knowledge` | 12 / 5 | `PageShell` + `EmptyState` | `a-c-tables-15` (search + export/filter header) and `a-c-tables-08` | `base/badge`, `base/input` | MED |
| `personas` | `#/personas` | 8 / 4 | — | `a-c-tables-08`, `a-c-form-layouts-04` | `base/textarea`, `base/checkbox` | MED |
| `dashboard` | `#/` | 3 / 4 | `.recruiting-*` bespoke | `a-c-empty-states-01` for the `is-empty` worklist queues; `a-c-statistics-11` if a metric row is added | `base/avatar`, `base/badge` | MED |
| `login` cluster | `#/login`, `#/forgot-password`, `#/reset-password` | 5 / 0 | bespoke `AuthShell` | none — audit for conformance only | `login/*` templates are whole-page scaffolds | LOW (already good) |
| `knowledge-base` | `#/knowledge-bases` | 4 / 0 | `PageShell` + `EmptyState` | `a-c-empty-states-01/03`; `a-c-tables-08` for the list header | **`base/badges` — first real install, done** | LOW |
| `automation` (bot runs) | `#/bot-runs` | 4 / 0 | `PageShell` + `EmptyState` | `a-c-timeline-01` for `bot_runs` (vertical guide + `size-3` markers + carded events) | `base/badge`, `base/table` | LOW |
| `kit` | — (shared) | 2 / 9 | already a Tailkit port | `a-c-empty-states-01/03`, `a-c-page-headings-03/04`, `a-c-tables-14/15`, `a-c-form-layouts-04/05`, `a-c-list-groups-05` | `foundations/*` | — (the seam) |

Untitled UI page templates were **not** evaluated as options: each is a 26–32
file whole-app scaffold carrying its own sidebar, nav-item, filter-bar and
pagination, plus `recharts` and `@internationalized/date`. Adopting one replaces
the react-admin shell rather than restyling a screen. Recorded as "would require
shell replacement — not recommended" for all 13 surfaces.

## Verified findings that changed the work

1. **`kit/` is the correct seam, and its doc comment was wrong.** `kit/index.ts`
   claimed the primitives "consume the `--tt-*` token bridge declared in
   `conversations/inbox/tokens.css`". They do not: `kit/tailkit-system.css`
   declares `--tt-*` on `.workspace-frame`, and the inbox *also* declares an
   overlapping `--tt-*` set (on `:root` at `inbox/tokens.css:2` and on
   `.workspace-frame` at `:223`), so on inbox routes the inbox's values win for
   the keys it declares. Both defects are fixed in `kit/index.ts`, and the
   remaining duplication is recorded as a follow-up below.
2. **`kit/index.ts` pointed at `plans/<timestamp>-tailkit-overhaul/`, which does
   not exist.** `check-doc-links.mjs` cannot see code comments, so nothing caught
   it. Fixed.
3. **`EmptyState` is the highest-leverage component in the app, but there are
   two of them.** `kit/EmptyState` (Tailkit anatomy, `--tt-*` tokens,
   `role="status"`, `action` slot) is consumed by `knowledge-base`, `users` and
   `automation`; `@/components/ui/empty-state` (shadcn, `data-slot="empty-state"`,
   `border-border/60 bg-muted/20`, `actions` slot) is consumed by `knowledge`,
   `projects` and `admin/data-table.tsx`. The plan's "one component, six
   surfaces" is therefore wrong: each implementation reaches three surfaces. The
   kit one was rebuilt on the verified dashed-frame anatomy at console density.
   Converging the shadcn one is a separate decision — `components/ui/` is
   dependency-owned, so the move is to repoint the two *app* consumers
   (`projects/ProjectList.tsx`, `knowledge/KnowledgeSourceList.tsx`) and leave
   `admin/data-table.tsx` on the registry's component.
4. **`__screenshots__/` directories are NOT regression baselines.** They are
   Vitest screenshot artifacts, gitignored and regenerated on every run
   (`.gitignore:79`). The only enforced visual baselines in the repository are the
   four Playwright login screenshots (unauthenticated routes only,
   `e2e/visual.spec.ts-snapshots/`). **No authenticated surface has enforced visual
   regression coverage**, which is why every restyle step below needs manual QA and
   why the plan's per-surface risk tiers should be read as *review* risk, not
   *automation* risk.
4. **The dashboard empty state has no visual baseline.** The three
   `RecruitingCommandCenter` baselines cover the error state, the chevron and
   candidate rows; `is-empty` is unguarded. Dashboard empty-state work needs
   manual QA.
5. **Three neutral ramps existed**: `--workspace-*` (console roles, `:root`),
   `--tt-*` (kit bridge), `--color-secondary-*` (Tailkit paste surface). They now
   have one owner for every slot where the value is shared: `--tt-surface-muted`,
   `--tt-surface-lift`, `--tt-border` and `--tt-ink-muted` alias
   `var(--color-secondary-100/50/200/500)`. The remaining `--tt-*` keys stay on
   `--workspace-*` because **no Tailkit shade carries the same value** —
   `--workspace-canvas` is the warm page tone `#fff6ed` while
   `--color-secondary-50` is the lightest surface `#fffcf8`; re-pointing them
   would move pixels on every workspace screen for no user-visible gain.
6. **`registry:gen` IS idempotent — the plan's claim was wrong.** Two consecutive
   runs produce byte-identical output (`diff` → no difference), and `glob` is
   `11.1.0` in both the pre-migration and current tree. The committed manifest had
   simply drifted: `6ec18bea chore(crm): publish leadLookupKey in the component
   registry` inserted the file by hand instead of regenerating, which left
   `candidateProfile.ts` before `leadLookupKey.ts` while the generator emits the
   reverse. The regenerated manifest (which also picks up this change's dependency
   ranges) is the fix.
7. **Tailwind emits `@theme` variables on use, not eagerly.** Verified against the
   built CSS: the new Untitled UI token layer adds ~11.5 kB of `:root` custom
   properties, and every unused token costs zero bytes. The larger CSS delta from
   installing `base/*` is the components' own utility classes, which Tailwind
   compiles because it scans files, not import graphs — see the pruned-components
   note in the Part B completion record.
8. **Four utility names are shared by both systems, and all four were already in
   use.** Exact-token counts across the console (excluding generated components):
   `text-primary` 18, `bg-primary` 4, `bg-secondary` 6, `border-primary` 2. Every
   other name Untitled UI defines (`text-tertiary`, `bg-tertiary`, `border-secondary`,
   `ring-primary`, `ring-secondary`, `ring-brand`, `outline-brand`,
   `text-error-primary`, `text-fg-quaternary`, `shadow-xs-skeuomorphic`, `text-md`,
   `text-display-*`, …) had **zero** console call sites, so it can safely carry the
   library's semantics. This measurement is what makes the `:root`/`.uu-scope`
   split in `src/styles/untitledui-theme.css` safe rather than hopeful.
9. **`npm run prettier` was failing on 23 files before this work**, and
   `tsc -p tsconfig.node.json` failed on a `types: ["faker"]` entry for a package
   that is no longer installed. Both are pre-existing and fixed (see the Part B
   completion record).

## Per-surface next action, in risk order

All thirteen surfaces have now been through the pass, in this order:

1. `knowledge-base` — ✅ `base/badges` installed and used for the mode pill.
2. `automation` — ✅ `a-c-timeline-01` rail on the `bot_runs` log; empty state
   from the shared kit component.
3. `knowledge`, `personas` — ✅ both on the kit `EmptyState`; `personas` list
   header and framed card list on `a-c-tables-08`.
4. `dashboard` — ✅ the `is-empty` queues previously rendered **nothing**; they
   now render `EmptyState`, with a regression test added where there was none.
5. `users` — ✅ real `<table>` table anatomy with a header strip and zebra rows.
6. `projects` — ✅ kit `EmptyState`; its table anatomy was not re-cut (the
   accordion list is deliberate) — recorded, not forced.
7. `integrations` — ✅ `a-c-form-layouts-04/05` title-rail + field-panel sections.
8. `conversations` — ✅ `a-c-chat-01` bubble corners and empty states only; the
   inbox was not restructured, and its dead CSS was consolidated.

Still open, deliberately: Untitled UI form primitives (`base/select`,
`base/combobox`, `base/dropdown`, `base/avatar`) in real routes — C3 step 2 — and
the inbox's duplicate `--tt-*` bridge (documented in `kit/index.ts`).

## Drop-in obligations (unchanged, and enforced in review)

1. Bind demo rows to real react-admin data — never ship `Nansi Hart` / `$49,00`.
2. Translate every user-facing string to Vietnamese; code and comments stay English.
3. Swap demo `hi-*` inline SVG for `lucide-react` or `@untitledui/icons`.
4. Scope feature CSS under the feature's own workspace class; `MAX_UNSCOPED_RULES`
   in `css-scoping.test.ts` may only go down.
5. Light theme only; strip `dark:` variants rather than half-styling a mode that
   cannot match.
6. Wrap Untitled UI subtrees in `.uu-scope` — outside it, `bg-primary`,
   `bg-secondary`, `text-primary` and `border-primary` keep the console's meaning
   and a library component renders with the wrong surface.
