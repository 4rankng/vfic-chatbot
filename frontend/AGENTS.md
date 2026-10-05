# AGENTS.md — TingHire frontend

## Project Overview

**TingHire** (formerly *Ting Ting*) is the recruiter/admin console for the
VFIC recruitment platform. It is a React + react-admin single-page app that
talks to the **VFIC FastAPI backend** (`/api/v1` REST + Socket.IO).
The UI is **Vietnamese-only**. It is derived from the open-source
*Atomic CRM* / *shadcn-admin-kit* template (by Marmelab) but has been
stripped to five recruitment-console resources.

> **History:** until 2026-06-26 this app used Supabase directly (PostgREST +
> Supabase Auth + Realtime). It has been **fully migrated to the FastAPI
> backend**. Any reference to Supabase, FakeRest, contacts/companies/deals/
> tasks/sales resources, or `supabase/schemas` as the source of truth is
> **stale template residue** and should be ignored.

## Development Commands

Real commands are **npm scripts** (`make help` lists the common ones).

```bash
npm install                 # install dependencies (also installs the git pre-commit hook)
npm run dev                 # Vite dev server -> http://localhost:5173
npm run typecheck           # tsc --noEmit (tsconfig.app.json)
npm run typecheck:node      # tsc --noEmit (tsconfig.node.json: the three config files)
npm run build               # tsc && vite build (production bundle)
npm run test:unit:app       # vitest unit tests
npm run lint                # eslint
npm run prettier            # prettier --check
make push                   # build + push ghcr.io/4rankng/tinghire-fe image (deploy)
```

`tsconfig.node.json` covers `vite.config.ts`, `vitest.config.ts` and
`playwright.config.ts`. Its `verbatimModuleSyntax` is deliberately `false`
because `vite-plugin-simple-html@1.1.0` resolves its `@swc/html` dependency to
that CommonJS package's raw TypeScript source, which the flag reports as an error
inside this type-only project. A **duplicate key** in that file is not a syntax
error for `tsc` (last one wins) but *is* fatal for Rolldown's strict JSON loader,
which fails the whole build and every Vitest browser import with
"Failed to load tsconfig … duplicate field" — so keep one copy of every key.

Point the app at a backend by setting `VITE_API_BASE` (defaults to the same
origin); see `src/lib/runtime-config.ts`.

## Architecture

### Technology Stack

- **Framework**: React 19 + TypeScript + Vite
- **Admin layer**: react-admin (ra-core) + shadcn-admin-kit (vendored, mutable)
- **UI**: Shadcn UI + Radix UI, **Tailwind CSS v4**
- **Data**: TanStack Query (via react-admin) against the FastAPI REST API
- **Realtime**: Socket.IO (WebSocket + polling fallback) at `/socket.io/`
- **Auth**: JWT (access + refresh) held in `localStorage`; see
  `src/components/atomic-crm/providers/rest/authProvider.ts`
- **Testing**: Vitest

### Data Source (single, REST)

One data provider: **`src/components/atomic-crm/providers/rest/dataProvider.ts`**
maps react-admin verbs onto `/api/v1/{resource}`. There is **no Supabase
client** and **no FakeRest** in production. The `providers/rest/` directory
replaced the misleading legacy provider directory name in 2026-06-26 (the
code was always REST).

Chat-specific ports live in `conversations/application/`; their REST and
Socket.IO adapters live in `conversations/infrastructure/` and
`providers/realtime/`. All HTTP adapters use `src/lib/apiClient.ts`.

### Resources

Compiled by `src/components/atomic-crm/capabilities/static-recruitment-runtime.ts`
from contributions in `capabilities/kernel/` and `capabilities/recruitment/`;
`root/CRM.tsx` renders that compiled runtime:

| Resource | Module | Purpose |
|---|---|---|
| `conversations` | `atomic-crm/conversations/` | Zalo chat inbox + thread |
| `projects` | `atomic-crm/projects/` | Recruitment project knowledge |
| `settings` | `atomic-crm/integrations/` | Channel integration settings |
| `users` | `atomic-crm/users/` | Admin user provisioning |

The CRM `users` resource maps to the backend `users` table (formerly Supabase
`profiles`). `RESOURCE_PATH` in the dataProvider keeps the legacy REST
aliases — `knowledge_bases` → `/api/v1/knowledge/knowledge-bases` and
`knowledge_sources` → `/api/v1/knowledge/documents` — none of which has an
admin page any more. There is no `personas` resource: the `Persona`,
`PersonaFollowupRule(s)`, and `AdapterPersonaAssignment` types and the
`personas` resource path were removed, and the agent persona is a backend code
constant (`app/prompts/vfic_persona.py`), not operator-editable content.

### Directory Structure

```
src/
├── components/
│   ├── admin/              # shadcn-admin-kit framework code (mutable dependency, vendored)
│   ├── ui/                 # Shadcn UI primitives (mutable dependency)
│   └── atomic-crm/         # The VFIC app
│       ├── capabilities/   # static runtime contributions and compilation
│       ├── conversations/  # domain/application/infrastructure/presentation
│       ├── dashboard/      # recruiter/admin dashboard
│       ├── layout/         # app shell, header, topbar, notifications
│       ├── leads/          # recruitment lead feature layers
│       ├── login/          # auth page
│       ├── projects/       # projects resource
│       ├── providers/      # REST/auth/i18n/realtime adapters
│       ├── reporting/      # reporting ports, domain logic, HTTP adapter
│       ├── root/           # <CRM> runtime renderer
│       ├── settings/       # settings + profile pages
│       ├── users/          # users resource
│       └── types.ts
├── lib/                    # apiClient.ts, runtime-config.ts, shared utilities
└── App.tsx                 # renders <CRM />
```

### Feature Layering

Features with non-trivial logic layer their files: `domain/` (pure logic, no
React and no IO), `application/` (ports + orchestration), `infrastructure/`
(adapters), `presentation/` (React components and hooks). Imports point along
that direction, and each test lives beside the module it covers rather than at
feature root. Simple features may stay flat.

### Mutable Dependencies

Vendored framework code that may be modified directly (this is intentional —
they are copy-paste dependencies, not npm packages):
- `src/components/admin/` — shadcn-admin-kit
- `src/components/ui/` — Shadcn UI

### Registry Publishing

`registry.json` publishes application TypeScript and CSS. The external admin
registry and named Shadcn dependencies supply `components/admin`,
`components/ui`, `hooks/use-mobile.ts`, and `lib/utils.ts`. PNG/WebP
illustrations under `src/assets/` remain application static assets because the
registry serializes file contents as UTF-8; they are path-checked but are not
embedded in the registry payload. SVGs are text, so the ones product code
imports (`facebook-messenger.svg`) are published.

`npm run registry:gen` rebuilds the manifest from globs and is idempotent
(verified byte-for-byte across consecutive runs); `npm run registry:check` fails
when a published file is missing, is test-only, or imports something
unpublished. Regenerate and review the diff before committing — it should only
add entries. The manifest has no CI job: GitHub Actions was removed in
`e7010b22`, so the gate runs in `frontend/.husky/pre-commit` (which also runs
`registry:gen` and prettier) and in the root `make release-check`. That hook is
installed by `npm install` — if `.git` reports no `pre-commit` hook, run
`npm run prepare` from `frontend/`, because without it the manifest and the
formatting drift silently (that is how `registry.json` fell out of sync with its
own generator once).

### Feature CSS Scoping

`.inbox-bg-container` is one shared container class carried by every workspace
root — inbox, profile, project and settings. A rule nesting
under it as a *descendant* (`.inbox-bg-container .x`) therefore reaches all four
screens. The scoped form is the compound selector `projects.css` already uses:
`.inbox-bg-container.project-workspace .x`.

Scope a stylesheet under its own workspace class the next time you edit it, and
lower `MAX_UNSCOPED_RULES` in `src/components/atomic-crm/css-scoping.test.ts` to
match. That test fails when the count grows, so new rules must be scoped rather
than added to the backlog. Do not batch-rewrite the remaining sheets: it needs
visual QA per screen (TEST-10 — the CSS tests assert source text, not rendered
layout).

### i18n

Vietnamese-only. `providers/commons/i18nProvider.ts` pins the locale to `vi`
and uses `vietnameseCrmMessages.ts`. Do not wire other locales into the app.

### Path Aliases

`@/components`, `@/lib`, `@/hooks`, `@/components/ui` (see `tsconfig.json`).

## Important Notes

- The app is **Vietnamese-only** in user-facing strings; code/identifiers/
  comments are English.
- Auth tokens live in `localStorage` under `RaStore.auth.*` (access + refresh);
  a 401 triggers one transparent refresh.

## UI/UX Component Sourcing

For any UI/UX design problem — a new screen, a component, a layout, an empty
state, a table, a form, a dashboard, or a "this looks wrong" complaint —
**consult the Untitled UI MCP before hand-writing Tailwind or inventing
markup.** That is the default, not an escalation path. The console renders on
one component layer; the parallel Tailkit layer it used to sit beside was
retired on 2026-09-30 and must not be reintroduced.

### Tailkit is retired — do not reintroduce it

Until 2026-09-30 the console carried a second, parallel system: a numeric
`--color-secondary-50…950` ramp in `src/styles/tailkit-tokens.css`, a `--tt-*`
token bridge in `kit/tailkit-system.css`, a Tailkit-redesign inbox sheet, and
two contract tests pinning them. All of it is gone (`4b7ccaf3`); the
load-bearing control geometry moved onto the daisyUI theme tokens. Two things
follow:

- No `--tt-*` custom property, Tailkit token file, or pasted Tailkit markup may
  come back. `tt-*` classes themselves are **daisyUI's prefix**
  (`@plugin "daisyui" { prefix: "tt-" }` in `src/index.css`), which the shadcn
  adapters in `components/ui/` still use — that layer is not Tailkit and is not
  going away.
- Tailkit's catalog remains a useful *reference* for console anatomy (a table,
  an empty state, a form layout). Read it for structure if that helps, then
  build the surface from the installed Untitled UI primitives and the console's
  own tokens.

### Untitled UI — installed, and the layer that makes it render

Two things are true at once: the design direction is still the primary value for
*layout* decisions, and its React components are now genuinely installable.

Design direction (no install needed):

- `mcp__untitledui__search_components`, `get_page_templates`,
  `get_component_suggestions`, `get_latest_components` — layout, hierarchy, and
  interaction patterns.
- `mcp__untitledui__search_icons` — `@untitledui/icons` is installed (1181
  exports). **Pass `category`**: free-text queries return 0 results, so
  `search_icons(query: "user")` finds nothing while
  `search_icons(query: "user", category: "users")` returns `User01`, `User02`,
  `UserCheck01`, … 41 results. Use the `importName` it returns verbatim as the
  import. Round-trip is covered by
  `src/components/atomic-crm/ui-design-dependencies.test.tsx`.

Installing a component (the toolchain migration landed 2026-09-28: Tailwind
4.3.3, React 19.2.4, Vite 8.3.1, React Aria runtime installed, so the CLI works):

```bash
npx untitledui@latest add badges --yes      # writes into src/components/base/**
npx untitledui@latest add input --yes       # pulls button/tags/tooltip siblings
```

- **Never run `npx untitledui upgrade` in this repository.** It rewrites
  `tsconfig.json` and `package.json` and drops `upgrade-report.json` /
  `UPGRADE-INSTRUCTIONS.md` at the project root. `add` is the only safe verb.
- Generated files are a **dependency-owned layer**: `src/components/base/`,
  `src/components/foundations/`, `src/utils/`, listed in
  `scripts/check-registry-paths.mjs` as `dependencyOwnedPaths` because the CLI's
  own imports target `@/components/base/...`. Do not hand-edit them; re-run the
  CLI. Do not move them under `components/ui/` or `components/admin/` — those
  belong to the external shadcn registry.
- **Only the components the app can reach are kept.** Tailwind scans *files*,
  not import graphs, so an unreachable generated file still compiles its
  utilities into the shipped CSS. The adopted set (application navigation,
  table, pagination, empty state, alerts, modals, activity feed, loading
  indicator, slideout menus, command menu, breadcrumbs, plus the base
  primitives the kit and the screens use) is what the app imports today.
  Re-check before adding a component back:

  ```bash
  node scripts/check-generated-reachability.mjs                                 # report
  node scripts/check-generated-reachability.mjs --keep=src/components/base/input/input.tsx
  ```

  It resolves `@/` and `./` static imports, seeds the traversal with the keep-set
  (so a kept component's own dependencies are not reported as dead) and prints
  what nothing reaches. It covers `components/base`, `components/application`,
  `components/shared-assets`, `components/foundations` and `utils`. Trust it
  before deleting; `npx untitledui add <component> --yes` re-installs anything
  pruned.
- **After any `add`, run `npm run prettier:apply`.** The CLI writes its own
  formatting, so a re-installed component can fail `npm run prettier` even though
  the file was clean before — which is how `src/utils/is-react-component.ts` kept
  reappearing in the diff. The pre-commit hook formats staged files, so a
  re-installed file that nobody stages stays unformatted until then.
- **React Aria controls inside a react-admin form must set
  `validationBehavior="aria"`.** Its default `native` behaviour sets the
  `required` attribute on the input, so the browser blocks the form's submit
  before react-admin's validation runs and the user gets a browser bubble instead
  of the console's Vietnamese error — a silent no-op save. Both adopted forms pin
  it: `aria-required` present, native `required` absent.
- **Wrap every Untitled UI subtree in `.uu-scope`.** The console and Untitled UI
  both define `bg-primary`, `bg-secondary`, `text-primary` and `border-primary`
  with different meanings; `src/styles/untitledui-theme.css` pins the console's
  meaning on `:root` and restores the library's inside `.uu-scope`. Rendering a
  component without the wrapper gives it the console's action fill (a slate
  block) instead of a white surface — the failure looks like unreadable text on
  a solid panel, not like a type error. `.workspace-chrome` is the inverse
  scope: it re-points the same vocabulary at the ink topbar and rail.
  `src/components/atomic-crm/untitledui-theme-contract.test.ts` guards the
  collision set.
- **Two primitive runtimes, two focus models.** React Aria (Untitled UI) and
  Radix (`components/ui`) must not be nested inside each other's subtrees. If a
  surface needs both, one component owns the whole subtree.
- Untitled UI page templates are **not** adopted: each is a 26–32 file whole-app
  scaffold carrying its own sidebar, nav, filter bar and pagination. Use them as
  reference only.

### The token contract (load-bearing)

An Untitled UI component only renders correctly because the names it compiles
against exist. Three files own that vocabulary, and the split is protected:

- **`src/index.css` owns the console's palette.** The daisyUI theme `tinghire`,
  the `:root` / `.dark` / `.kb-scope` semantic slots, the slate ramp, the chart
  colours and the sonner toast variables are all defined here, once. Feature
  sheets consume these names; they never redeclare them.
- **`src/styles/untitledui.css` is the library's base import**, and
  `src/styles/untitledui-theme.css` is its vocabulary: `--color-utility-*`, the
  `--color-bg-*` / `--color-text-*` alias families, the
  `--background-color-*` / `--text-color-*` / `--border-color-*` /
  `--ring-color-*` / `--outline-color-*` namespaces, `--text-md` /
  `--text-display-*`, and the `--color-brand-50…950` mapping onto the console's
  `--color-uu-brand-*` ramp. It is imported exactly once, from the app entry.
- **Four utility names are defined by both systems** — `bg-primary`,
  `bg-secondary`, `text-primary`, `border-primary` — and Tailwind resolves
  `bg-primary` from `--background-color-primary` the moment that key exists. The
  theme file pins those four to the console's `var(--primary)` /
  `var(--secondary)` on `:root` and restores the library's meaning inside
  `.uu-scope` (see above).
  `src/components/atomic-crm/untitledui-theme-contract.test.ts` fails if a
  future token would capture a fifth console name, if the four bindings move, or
  if the layer starts redeclaring the console's type, radius, shadow or font
  scale.

Treat these as protected too:

- **Never redeclare a flat console token in the theme layer**, and never
  redefine `--radius` or the `--shadow-*` names the console owns. A second
  declaration is how one utility ends up with two meanings.
- **A library component rendering unstyled is a missing token, not a styling
  bug.** Add the name to `src/styles/untitledui-theme.css`; never patch it with
  an `!important` override in a feature sheet.
- Tailwind emits `@theme` variables **on use**, not eagerly, so a fresh build
  will not contain every mapped name until a component actually references one.
  That is correct behaviour, not a broken import.
