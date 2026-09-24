# TingHire

TingHire (formerly Ting Ting / VFIC miniCRM) is a Vietnamese recruiting
chatbot + recruiter console built on Zalo. Candidates chat with an LLM agent
about job openings; recruiters take over conversations and manage the job
board from a web console. Production: `bot.tingting.vip` (DigitalOcean,
2 vCPU / 4 GB).

## Repository layout

- `backend/` — Python 3.12 / FastAPI, LangGraph-style bot-turn pipeline,
  PostgreSQL 16 + pgvector, Redis, RQ workers. See [`TECH.md`](TECH.md) for
  the stack map and [`docs/system-architecture.md`](docs/system-architecture.md)
  for the request lifecycle and queue model.
- `frontend/` — React 19 + ra-core (react-admin headless) + Vite +
  TypeScript strict, Tailwind v4 + shadcn/ui. Product code lives in
  `frontend/src/components/atomic-crm/`.
- `docs/` — architecture, standards, deployment guide, troubleshooting.
- `standards/` — coding style, security/performance baselines, and the
  agent completion checklist.
- `plans/reports/` — per-change completion records.
- `kanban/` — the team's ticket board.

## Quickstart (local dev)

Prerequisites: Python ≥ 3.12,< 3.13 and Node 22 (see `frontend/.nvmrc`).

```bash
make bootstrap   # one-time: backend venv + frontend install
make dev         # Postgres + Redis + Adminer + backend + workers + Zalo mock + frontend
make seed        # load Vietnamese dev fixture data (make dev does NOT seed)
```

Then open `http://localhost:5173` and log in with `admin@vfic.dev` /
`admin123` (dev seed credentials).

## Verification and deployment

- `make release-check` — the pre-deploy gate (lint, tests, integration
  suite, frontend build + Playwright, golden correctness check).
- `make deploy` — blue/green cutover, smoke-gated; `make rollback` flips
  back in ~1s. Read [`docs/deployment-guide.md`](docs/deployment-guide.md)
  in full before any deploy.

## For coding agents

Read [`AGENTS.md`](AGENTS.md) first — it is the always-loaded constitution
with the non-negotiable boundaries, approval gates, and the scoped workflow.
