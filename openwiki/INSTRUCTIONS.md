# OpenWiki brief — TingTing

This brief steers OpenWiki when documenting TingTing. It is owned by the team;
OpenWiki reads it but never rewrites it during normal runs.

## What TingTing is

TingTing (Ting Ting) is a Vietnamese trucking logistics platform for managing
trips, drivers, customers, fleet vehicles, and financials (ledger, P&L, debt
tracking, profit distribution). The codebase is a TypeScript monorepo with three
packages:

- `backend/` — Express v5 + TypeScript API on port 3090; Drizzle ORM with
  PostgreSQL; JWT auth + Casbin RBAC.
- `frontend/` — React 18 + Vite + TypeScript on port 5173; TanStack Query,
  React Router, Recharts. Vietnamese-first copy, mobile-optimized driver
  pages.
- `shared/` — Shared TypeScript types, Zod schemas, financial calculations
  (`round2dp`, `computeTripTotals`), constants.

The currency is Vietnamese đồng (VND), displayed with no decimal places.

## Roles

| Role | Vietnamese | Scope |
|------|-----------|-------|
| ADMIN | Quản trị | Full access |
| MANAGER | Giám đốc | Trips, financials, fleet, reports |
| ACCOUNTANT | Kế toán | Financials, debt, P&L |
| DRIVER | Lái xe | Own trips, earnings, mobile pages |

## Where to look first

- `AGENTS.md` (root) and `TECH.md` — system map, stack, monorepo overview.
- `docs/codebase-summary.md` — repository map.
- `docs/system-architecture.md` — architecture.
- `docs/code-standards.md` and `standards/coding-style.md` — code conventions.
- `docs/testing.md` — testing approach.
- `standards/agent-completion-checklist.md` — completion record template.
- `docs/flows/DELIVERY_TRIP_LIFECYCLE.md` — trip lifecycle QA + user manual.
- `docs/company-files/` — original Vietnamese business documents (fuel norms,
  allowances, vehicle data).

## Key boundaries to preserve

- API transport lives in `backend/src/routes/`; business logic lives in
  `backend/src/services/`. Do not collapse them in the docs.
- The trip lifecycle (`PENDING → IN_PROGRESS → COMPLETED → SETTLED`) is the
  central domain flow. It deserves a dedicated workflow page.
- Financial precision is mandatory: docs must reference `round2dp()` and
  `computeTripTotals()` from `shared/src/calculations/` for any monetary math.
- RBAC enforcement is layered (Casbin policies + middleware). Both layers
  deserve a page.
- Demo mode is permanently disabled — the frontend uses the real API only.

## Conventions

- TypeScript strict mode — no `any` types.
- REST API with `/api/v1` prefix.
- Drizzle ORM for all database queries — no raw SQL.
- Vietnamese-first UI copy.
- Avoid undocumented public-contract changes.

## Task tracking

`TASKS.md` in the project root describes two tracks:

- Track 1 — E2E Trip Lifecycle Epic (Phases 1–4).
- Track 2 — Feature backlog (fuel norms, receivables, dashboard, profit
  distribution, tech debt).

When documenting work-in-progress features, link to the corresponding `TASKS.md`
item and the relevant phase in `plans/`.

## What to emphasize in pages

- System responsibility and ownership, not just symbol inventories.
- Runtime/build entrypoints (`backend/src/index.ts`, `frontend/src/App.tsx`).
- Mechanisms and control/data flow across the backend/frontend/shared split.
- Upstream/downstream relationships (DB, map providers, file uploads, RBAC).
- State, persistence, ordering, and lifecycle for the trip and ledger.
- Invariants and failure behavior (auth, RBAC denial, financial rounding).
- Configuration, security, and operational consequences.
- Extension seams for the planned Track 2 features.

## What to omit

- Pages that only mirror a directory or list symbols without explaining a
  system.
- Pages that repeat `docs/codebase-summary.md` verbatim — cross-link instead.
- Speculative behavior not present in the current source.
- Lockfiles, generated bundles, and any path matched by `.openwikiignore`.

## Language

Generate factual pages in English. Keep Vietnamese domain terms (Quản trị,
Giám đốc, Kế toán, Lái xe, đồng, etc.) in italics on first use and use them
consistently across pages.