# AGENTS.md — TingHire frontend

## Project Overview

**TingHire** (formerly *Ting Ting*) is the recruiter/admin console for the
VFIC recruitment platform. It is a React + react-admin single-page app that
talks to the **VFIC FastAPI backend** (`/api/v1` REST + Socket.IO).
The UI is **Vietnamese-only**. It is derived from the open-source
*Atomic CRM* / *shadcn-admin-kit* template (by Marmelab) but has been
stripped to eight recruitment-console resources.

> **History:** until 2026-06-26 this app used Supabase directly (PostgREST +
> Supabase Auth + Realtime). It has been **fully migrated to the FastAPI
> backend**. Any reference to Supabase, FakeRest, contacts/companies/deals/
> tasks/sales resources, or `supabase/schemas` as the source of truth is
> **stale template residue** and should be ignored.

## Development Commands

Real commands are **npm scripts** (`make help` lists the common ones).

```bash
npm install                 # install dependencies
npm run dev                 # Vite dev server -> http://localhost:5173
npm run typecheck           # tsc --noEmit (tsconfig.app.json)
npm run build               # tsc && vite build (production bundle)
npm run test:unit:app       # vitest unit tests
npm run lint                # eslint
npm run prettier            # prettier --check
make push                   # build + push ghcr.io/4rankng/tinghire-fe image (deploy)
```

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
| `bot_runs` | `atomic-crm/automation/` | Bot execution audit trail (read-only) |
| `knowledge_sources` | `atomic-crm/knowledge/` | Knowledge document admin |
| `knowledge_bases` | `atomic-crm/knowledge-base/` | Knowledge-base admin |
| `projects` | `atomic-crm/projects/` | Recruitment project knowledge |
| `personas` | `atomic-crm/personas/` | Agent persona admin |
| `settings` | `atomic-crm/integrations/` | Channel integration settings |
| `users` | `atomic-crm/users/` | Admin user provisioning |

The CRM `users` resource maps to the backend `users` table (formerly Supabase
`profiles`). The legacy `knowledge_sources` name targets the backend
`/api/v1/knowledge/documents` route (see `RESOURCE_PATH` in the dataProvider).

### Directory Structure

```
src/
├── components/
│   ├── admin/              # shadcn-admin-kit framework code (mutable dependency, vendored)
│   ├── ui/                 # Shadcn UI primitives (mutable dependency)
│   └── atomic-crm/         # The VFIC app
│       ├── automation/     # bot_runs
│       ├── capabilities/   # static runtime contributions and compilation
│       ├── conversations/  # domain/application/infrastructure/presentation
│       ├── dashboard/      # recruiter/admin dashboard
│       ├── knowledge/      # knowledge_sources admin
│       ├── knowledge-base/ # knowledge_bases admin
│       ├── layout/         # app shell, header, topbar, notifications
│       ├── leads/          # recruitment lead feature layers
│       ├── login/          # auth page
│       ├── personas/       # personas resource
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

`npm run registry:gen` rebuilds the manifest from globs and must stay
idempotent; `npm run registry:check` fails the `frontend-quality` CI job when a
published file is missing, is test-only, or imports something unpublished.
Regenerate and review the diff before committing — it should only add entries.

### Feature CSS Scoping

`.inbox-bg-container` is one shared container class carried by every workspace
root — inbox, profile, project, persona, settings and knowledge. A rule nesting
under it as a *descendant* (`.inbox-bg-container .x`) therefore reaches all six
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
**consult the Untitled UI and Tailkit MCPs before hand-writing Tailwind or
inventing markup.** That is the default, not an escalation path.

### Tailkit — the drop-in system for console anatomy

Tailkit is plain React JSX + Tailwind utilities + inline Heroicons SVG. **It
needs no installed package**, so it works today.

```
mcp__tailkit__browse_catalog  (level=categories → subcategories → components)
mcp__tailkit__search_components / get_component_code (tech: "react")
```

Identifiers are `<letter>-c-<subcategory>-<nn>`; the recruiter console is the
`application-ui` package, so `a-c-tables-08`, `a-c-empty-states-03`,
`a-c-form-layouts-04`, `a-c-statistics-11`, `a-c-navigation-*`. Paste with
`get_page_templates`-free, direct retrieval; the response is ready JSX.

**Drop-in obligations — the pasted component is not the deliverable:**

1. Keep the JSX; **bind the demo rows to real react-admin data** instead of the
   hard-coded `Nansi Hart` / `$49,00` placeholders.
2. **Translate every user-facing string to Vietnamese.** Code, identifiers, and
   comments stay English.
3. **Swap demo `hi-*` inline SVGs** for `lucide-react` (the app's icon library)
   or `@untitledui/icons` once Phase 2 lands, where an equivalent already exists.
4. **Scope feature CSS under the feature's own workspace class.** Do not add to
   the unscoped backlog, and do not lower `MAX_UNSCOPED_RULES` in
   `css-scoping.test.ts` — that number may only go down.
5. Light theme only. `dark:` variants compile but never match; strip them when
   they add noise rather than styling a mode that does not exist.

### Untitled UI — design direction today, components after Phase 3

Use freely, no install required:

- `mcp__untitledui__search_components`, `get_page_templates`,
  `get_component_suggestions`, `get_latest_components` — layout, hierarchy, and
  interaction patterns. This is its main value right now.
- `mcp__untitledui__search_icons` — `@untitledui/icons` is installed (1181
  exports). **Pass `category`**: free-text queries return 0 results, so
  `search_icons(query: "user")` finds nothing while
  `search_icons(query: "user", category: "users")` returns `User01`, `User02`,
  `UserCheck01`, … 41 results. Use the `importName` it returns verbatim as the
  import. Round-trip is covered by
  `src/components/atomic-crm/ui-design-dependencies.test.tsx`.

**Its React components are NOT yet installable.** Every base component and every
page template declares `react-aria-components@^1.21.1` + `@untitledui/icons`,
and Untitled UI v8 sets minimums of Tailwind `^4.2.2`, React `^19.2.4`, and
**Vite `^8.0.0`**. This app is on Tailwind 4.1.18 / React 19.1.0 / Vite 7.3.6, and
`@vitejs/plugin-react@4.7.0` peer-excludes Vite 8. Do not paste React Aria markup
until that migration lands.

**Never run `npx untitledui upgrade` in this repository.** It rewrites
`tsconfig.json` and `package.json` and drops `upgrade-report.json` and
`UPGRADE-INSTRUCTIONS.md` at the project root. Only `npx untitledui add …` is
safe, and only after Phase 3. Keep any generated component out of
`src/components/ui/` and `src/components/admin/` — those are `dependencyOwnedPaths`
owned by the external shadcn registry.

### The token contract (load-bearing)

A pasted Tailkit component only renders correctly because
`src/styles/tailkit-tokens.css` defines the numeric `--color-secondary-50…950`
scale, the default palette stays intact, `ring-3`/`shadow-xs` compile, and
`hi-*` needs no CSS. Treat these as protected:

- **Never declare `--color-secondary` (no numeric suffix)** in
  `src/styles/tailkit-tokens.css`. It is a different utility from
  `--color-secondary-50` in Tailwind v4, but the flat slot is a live shadcn
  semantic that `src/index.css` redefines five times. A pasted component
  rendering unstyled is almost always a missing *shaded* token — add the shade
  to the token file, never an `!important` override in a feature sheet.
- Do not redefine `--radius` or the `--shadow-*` names the console owns.
- Tailwind emits `@theme` variables **on use**, not eagerly, so a fresh build
  will not contain `--color-secondary-*` until a component actually references
  one. That is correct behaviour, not a broken import.
- `src/components/atomic-crm/tailkit-contract.test.ts` asserts the scale, the
  single import, and the "never override `--color-secondary`" rule. Extend it
  when a Tailkit component needs a shade that does not exist yet.
