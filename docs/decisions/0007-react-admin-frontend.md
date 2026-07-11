# ADR-0007: react-admin for the Recruiter Console SPA

- **Status:** Accepted
- **Date:** 2026-06-26
- **Decider:** Project lead

## Context

The recruiter console needs:
- CRUD interfaces for leads, jobs, users, personas, knowledge documents, projects.
- A custom inbox (conversation list + chat thread) with realtime updates.
- Role-based access control (admin vs. recruiter).
- i18n (Vietnamese only).
- Data fetching with caching, optimistic updates, and auto-refresh.

Options considered: Custom React + TanStack Query, Next.js + custom admin, react-admin, Refine.

## Decision

Use **react-admin 5** (`ra-core`, `ra-i18n-polyglot`) as the admin framework, with a custom REST dataProvider and authProvider.

Key reasons:
- **CRUD scaffolding.** react-admin's `<Resource>` + `<List>` / `<Show>` / `<Create>` / `<Edit>` components generate standard CRUD UIs with minimal code. Saves weeks of building forms, tables, pagination, and filters from scratch.
- **DataProvider abstraction.** The `DataProvider` interface decouples the UI from the API. Custom REST provider in `providers/rest/dataProvider.ts` maps react-admin verbs to `/api/v1` endpoints.
- **TanStack Query integration.** react-admin 5 uses TanStack Query under the hood — we get caching, invalidation, and optimistic updates for free. A module-level `QueryClient` singleton controls staleTime (30s) and gcTime (24h).
- **Auth provider.** react-admin's `AuthProvider` interface handles login, logout, checkAuth, getIdentity. Custom JWT implementation in `providers/rest/authProvider.ts`.
- **i18n.** `ra-i18n-polyglot` with a Vietnamese-only catalog.
- **Custom routes.** react-admin allows `<CustomRoutes>` for non-CRUD pages (inbox, dashboard, performance, integrations).

## Consequences

- **Positive:** Rapid CRUD development. Consistent UI patterns. Built-in pagination, filtering, sorting. TanStack Query caching for free.
- **Negative:** react-admin's conventions can be restrictive for highly custom UIs (the inbox/chat thread required significant custom work in `atomic-crm/conversations/`). The `components/admin/` layer (~87 components from shadcn-admin-kit) is a large dependency surface.
- **Neutral:** Three component layers: `ui/` (shadcn primitives) → `admin/` (framework) → `atomic-crm/` (product). This separation keeps product code isolated from framework code.

## Related

- App root: `frontend/src/components/atomic-crm/root/CRM.tsx`
- DataProvider: `frontend/src/components/atomic-crm/providers/rest/dataProvider.ts`
- AuthProvider: `frontend/src/components/atomic-crm/providers/rest/authProvider.ts`
- i18n: `frontend/src/components/atomic-crm/providers/commons/i18nProvider.ts`
- Access control: `frontend/src/components/atomic-crm/providers/commons/canAccess.ts`
- [ADR-0008](0008-tailwindcss-v4-css-first.md) — styling system
