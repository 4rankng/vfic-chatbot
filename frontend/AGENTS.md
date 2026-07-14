# AGENTS.md — VFIC Chatbot (Ting Ting) frontend

## Project Overview

**VFIC Chatbot** (brand *Ting Ting*) is the recruiter/admin console for the
VFIC recruitment platform. It is a React + react-admin single-page app that
talks to the **VFIC FastAPI backend** (`/api/v1` REST + `/realtime` SSE).
The UI is **Vietnamese-only**. It is derived from the open-source
*Atomic CRM* / *shadcn-admin-kit* template (by Marmelab) but has been
stripped to five resources.

> **History:** until 2026-06-26 this app used Supabase directly (PostgREST +
> Supabase Auth + Realtime). It has been **fully migrated to the FastAPI
> backend**. Any reference to Supabase, FakeRest, contacts/companies/deals/
> tasks/sales resources, or `supabase/schemas` as the source of truth is
> **stale template residue** and should be ignored.

## Development Commands

Real commands are **npm scripts** (the `Makefile`'s `supabase-*` targets are
stale template leftovers and do not apply to VFIC).

```bash
npm install                 # install dependencies
npm run dev                 # Vite dev server -> http://localhost:5173
npm run typecheck           # tsc --noEmit (tsconfig.app.json)
npm run build               # tsc && vite build (production bundle)
npm run test:unit:app       # vitest unit tests
npm run lint                # eslint
npm run prettier            # prettier --check
make push                   # build + push franknguyenvd/vfic-frontend image (deploy)
```

Point the app at a backend by setting `VITE_API_URL` (defaults to the same
origin `/api/v1`); see `src/lib/vfic/config.ts`.

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
was renamed from `providers/supabase/` in 2026-06-26 (the old name was
misleading — the code was always REST).

Chat-specific calls (message history, last-message snippets, SSE subscribe)
live in `src/components/atomic-crm/conversations/chatRepository.ts` and
`src/lib/vfic/humanReplyService.ts`, which use the same REST client.

### Resources

Declared in `src/components/atomic-crm/root/CRM.tsx`:

| Resource | Module | Purpose |
|---|---|---|
| `conversations` | `atomic-crm/conversations/` | Zalo chat inbox + thread |
| `bot_runs` | `atomic-crm/automation/` | Bot execution audit trail (read-only) |
| `knowledge_sources` | `atomic-crm/knowledge/` | RAG document admin (read-only) |
| `users` | `atomic-crm/profiles/` | Admin user provisioning |

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
│       ├── conversations/  # inbox + chat thread + chatRepository
│       ├── dashboard/      # recruiter/admin dashboard
│       ├── knowledge/      # knowledge_sources admin
│       ├── layout/         # app shell, header, topbar, notifications
│       ├── login/          # auth page
│       ├── profiles/       # users resource
│       ├── providers/      # dataProvider + authProvider + i18n (REST, not Supabase)
│       ├── root/           # <CRM> root component (resource registration)
│       ├── settings/       # settings + profile pages
│       ├── consts.ts / types.ts
├── lib/vfic/               # config.ts (API/SSE URLs), humanReplyService.ts
└── App.tsx                 # renders <CRM />
```

### Mutable Dependencies

Vendored framework code that may be modified directly (this is intentional —
they are copy-paste dependencies, not npm packages):
- `src/components/admin/` — shadcn-admin-kit
- `src/components/ui/` — Shadcn UI

### i18n

Vietnamese-only. `providers/commons/i18nProvider.ts` pins the locale to `vi`
and uses `vietnameseCrmMessages.ts` (with `englishCrmMessages.ts` as the
fallback catalog). Do not wire other locales into the app.

### Path Aliases

`@/components`, `@/lib`, `@/hooks`, `@/components/ui` (see `tsconfig.json`).

## Important Notes

- The app is **Vietnamese-only** in user-facing strings; code/identifiers/
  comments are English.
- Auth tokens live in `localStorage` under `RaStore.auth.*` (access + refresh);
  a 401 triggers one transparent refresh.
- The `Makefile` `supabase-*` targets and `scripts/supabase-*.mjs` helpers are
  stale Atomic-CRM template leftovers and are not used by VFIC.
