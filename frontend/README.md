# TingHire frontend

Recruiter/admin console for the VFIC recruitment platform. Vietnamese-only
single-page app (React 19 + TypeScript + Vite + Tailwind CSS v4 +
react-admin) talking to the VFIC FastAPI backend (`/api/v1` REST +
Socket.IO). Repository-wide conventions live in the root
[AGENTS.md](../AGENTS.md); frontend specifics in
[AGENTS.md](./AGENTS.md).

## Commands

Real commands are the npm scripts (`make help` mirrors the common ones):

```bash
npm install                 # install dependencies
npm run dev                 # Vite dev server -> http://localhost:5173
npm run typecheck           # tsc --noEmit (tsconfig.app.json)
npm run build               # tsc && vite build (production bundle)
npm run test:unit:app       # vitest unit tests (browser project)
npm run test:unit:claude    # vitest agent-harness hook tests (node project)
npm run lint                # eslint
npm run prettier            # prettier --check
make push                   # build + push ghcr.io/4rankng/tinghire-fe image (deploy)
```

Point the app at a backend by setting `VITE_API_BASE` (defaults to the same
origin); see `src/lib/runtime-config.ts`.

## Layout

Product code lives in `src/components/atomic-crm/`; `src/components/admin/`
(shadcn-admin-kit) and `src/components/ui/` (shadcn UI) are vendored,
mutable dependencies. See `./AGENTS.md` for the resource map and dependency
direction.

QA probe scripts live in `qa/` (see `../docs/qa-runbook.md`).

## Attribution

Derived from [Atomic CRM](https://github.com/marmelab/atomic-crm) /
shadcn-admin-kit by Marmelab (MIT).
