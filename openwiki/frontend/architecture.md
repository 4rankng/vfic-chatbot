---
type: architecture
title: Frontend architecture and the atomic-crm recruitment console
description: Three-layer dependency direction (atomic-crm → admin → ui), bootstrap and PWA service worker, runtime generation reset on authority bumps, and how the console is wired to the FastAPI backend.
tags: [frontend, react, react-admin, vite, atomic-crm, shadcn-admin-kit, rq, socketio]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
sources:
  - id: openwiki-source-e483fd3285d99d05c7b265cf
    resource: repo://frontend/AGENTS.md
  - id: openwiki-source-454c9bcdde0b77b35e0fc994
    resource: repo://frontend/src/App.tsx
  - id: openwiki-source-f815c9b954867fc7c0e8385c
    resource: repo://frontend/src/components/atomic-crm/capabilities/static-recruitment-runtime.ts
  - id: openwiki-source-81c3888c48d7ce3a3e6c8f28
    resource: repo://frontend/src/components/atomic-crm/providers/rest/dataProvider.ts
generated: { by: "opencode", at: "2026-09-21T02:42:43.794Z" }
---

The frontend is TingHire's recruiter/admin console: a React 19 + TypeScript
single-page app, built on react-admin (ra-core) and a vendored shadcn-admin-kit
template, that talks to the FastAPI backend over REST and Socket.IO. It is
**Vietnamese-only** in user-facing strings.

## Three-layer dependency direction

Product code lives in `frontend/src/components/atomic-crm/`. The dependency
direction is strictly one-way:

```
atomic-crm  →  admin  →  ui
```

- **`src/components/atomic-crm/`** — the VFIC app. Owns business logic,
  capability contributions, presentation, and infrastructure adapters.
- **`src/components/admin/`** — the vendored shadcn-admin-kit framework
  code. Mutable on purpose (it is a copy-paste dependency, not an npm
  package), but never extended with VFIC business logic.
- **`src/components/ui/`** — Shadcn UI primitives (Radix UI + Tailwind v4).
  Same story as `admin/`.

Imports must never point "up" the chain: an `admin/` file cannot import
from `atomic-crm/`, and a `ui/` file cannot import from `admin/`.

## App bootstrap

`src/App.tsx` mounts the admin app. The runtime that the shell renders
is **statically compiled** at build time by
`src/components/atomic-crm/capabilities/static-recruitment-runtime.ts`
from contributions under `capabilities/kernel/` and
`capabilities/recruitment/`. `src/components/atomic-crm/root/CRM.tsx`
renders the compiled runtime. Adding a new resource means:

1. Writing the `capabilities/recruitment/` contribution.
2. Re-running the static runtime compiler.
3. Building the app.

No runtime registration.

## Data layer

- One data provider: `src/components/atomic-crm/providers/rest/dataProvider.ts`
  maps react-admin verbs onto `/api/v1/{resource}`. There is **no
  Supabase client** and no FakeRest in production.
- Chat-specific ports live in `conversations/application/`; their REST
  and Socket.IO adapters live in `conversations/infrastructure/` and
  `providers/realtime/`. All HTTP adapters use `src/lib/apiClient.ts`.
- Realtime: Socket.IO (WebSocket + polling fallback) at `/socket.io/`.
  Auth tokens live in `localStorage` under `RaStore.auth.*` (access +
  refresh); a 401 triggers one transparent refresh.

## Vietnamese-only

`providers/commons/i18nProvider.ts` pins the locale to `vi` and uses
`vietnameseCrmMessages.ts`. Do not wire other locales into the app.

## Resources

The compiled runtime currently surfaces eight resources (see
`frontend/AGENTS.md`):

| Resource | Module |
|---|---|
| `conversations` | `atomic-crm/conversations/` |
| `bot_runs` | `atomic-crm/automation/` |
| `knowledge_sources` | `atomic-crm/knowledge/` |
| `knowledge_bases` | `atomic-crm/knowledge-base/` |
| `projects` | `atomic-crm/projects/` |
| `personas` | `atomic-crm/personas/` |
| `settings` | `atomic-crm/integrations/` |
| `users` | `atomic-crm/users/` |

The `users` resource maps to the backend `users` table (formerly Supabase
`profiles`). The legacy `knowledge_sources` name targets the backend
`/api/v1/knowledge/documents` route (see `RESOURCE_PATH` in the
dataProvider).

## Auth + access

- JWT (access + refresh) in `localStorage` (`RaStore.auth.*`).
- The frontend access filter is in
  `src/components/atomic-crm/providers/commons/canAccess.ts` — a
  three-filter UX layer (action, availableResources, role). See
  [openwiki/access/rbac-and-capabilities.md](../access/rbac-and-capabilities.md).
- Admin-only routes return 403 from the backend; the UI mirror never
  relies on the client gate for security.

## Commands

Real commands are `npm` scripts (root `Makefile`'s `help` lists the
common ones):

```bash
npm install
npm run dev                 # Vite dev -> http://localhost:5173
npm run typecheck           # tsc --noEmit (tsconfig.app.json)
npm run build               # tsc && vite build (production bundle)
npm run test:unit:app       # vitest unit tests
npm run lint                # eslint
npm run prettier           # prettier --check
make push                   # build + push ghcr.io/4rankng/tinghire-fe
```

The backend is selected via `VITE_API_BASE` (defaults to the same origin);
see `src/lib/runtime-config.ts`.

## Path aliases

- `@/components`, `@/lib`, `@/hooks`, `@/components/ui` (see
  `tsconfig.json`).

## What the frontend never does

- No Supabase client. The PostgREST / Realtime / Auth SDKs were removed
  on 2026-06-26; any reference to them is stale template residue.
- No FakeRest / atomic-crm demo resources (`contacts`, `companies`,
  `deals`, `tasks`, `sales`). The template was stripped to eight
  recruitment-console resources.
- No additional locales wired into i18nProvider.
