# Ting Ting chatbot (VFIC recruitment platform)

Candidate conversations over Zalo (Bot Platform + Official Account) and
Facebook Messenger, with an admin/recruiter console: leads, knowledge base,
personas, bot runs, dashboards. Answers come from a LangGraph agent with
retrieval grounding and provider failover.

## One-command bootstrap

```bash
make dev
```

`make dev` first runs `make bootstrap`, which is idempotent: it creates
`backend/.env` from `backend/.env.example` (first run only), creates
`backend/.venv` and installs `backend[dev]` into it, and runs `npm ci` in
`frontend/` if `node_modules` is missing. Python 3.12 is what production and CI
run (`backend/.python-version`); the bootstrap warns if your default `python3`
differs.

First run also seeds the dev database (`backend/scripts/seed_dev.py` via
`make seed`). Console login after seeding: `admin@vfic.dev` / `admin123`.

## Layout

| Path | What lives there |
|---|---|
| `backend/app/` | FastAPI app: `api/` (transport) → `services/` (logic) → `models/` (hand-written Alembic schema), `graph/` behind `graph/ports.py` |
| `backend/alembic/` | 56 migrations; models never generate them |
| `frontend/src/` | React + Vite console (`components/atomic-crm/`) |
| `docs/` | Architecture, deployment, testing, runbooks |
| `kanban/` | Tech-debt board: four column folders, one card per file |
| `scripts/kanban/` | Board generator + ticket data (`python3 scripts/kanban/build.py`) |
| `standards/` | Review/definition-of-done checklists, completion checklist |

## Commands

- `make dev` — local stack (backend :8000, frontend :5173, Postgres/Redis/Adminer in Docker)
- `make seed` — seed dev data; `make adminer` — DB UI
- `make release-check` — the gate every release must pass (clean tree, lockfile, single alembic head, both test lanes, frontend build + e2e, golden pass rate)
- `make deploy` / `make rollback` — blue/green, smoke-gated, reversible
- `make backup` / `make backup-full` / `make restore` / `make restore-prod` — DB and full-droplet backup/restore (`docs/DROPLET-BACKUP-RESTORE.md` is the runbook)
- `cd backend && .venv/bin/pytest -m "not integration"` — backend unit lane

## Docs worth reading first

- `TECH.md` — system map and stack
- `docs/deployment-guide.md` — deploy, knobs, rollback (read it in full before deploying)
- `docs/testing.md` — the lanes and what each one is responsible for
- `docs/codebase-summary.md` — repository map
- `AGENTS.md` — the contract coding agents work under
