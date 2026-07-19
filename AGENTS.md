# AGENTS.md — Ting Ting Engineering Constitution

This file is the small, always-loaded contract for coding agents. Load linked
documents only when the task needs them. Start with `TECH.md` for the system map.

## Product and stack

Ting Ting / VFIC miniCRM is a Vietnamese recruiting chatbot and recruiter
console built on Zalo. Production is `bot.tingting.vip` on a 2 vCPU DigitalOcean
droplet.

- Backend: Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL + pgvector, Redis/RQ.
- Bot: manual LangGraph-style pipeline under `backend/app/graph/`.
- Frontend: React 19, TypeScript strict, react-admin 5, Vite 7, Tailwind v4.
- Interfaces: `/api/v1` REST and Socket.IO realtime.

Authoritative references:

- System overview: `TECH.md`
- Repository map: `docs/codebase-summary.md`
- Architecture: `docs/system-architecture.md`
- Code conventions: `docs/code-standards.md`, `standards/coding-style.md`
- Security/performance: `standards/security.md`, `standards/performance.md`
- Testing: `docs/testing.md`
- Definition of done: `standards/definition-of-done.md`

## Architecture boundaries

- `backend/app/api/` owns HTTP transport; business logic belongs in services.
- `backend/app/services/` owns business logic and depends on models/core or graph
  Protocols, not API modules.
- `backend/app/graph/` owns bot-turn behavior and depends on Protocol interfaces
  from `graph/ports.py`; wire concrete dependencies in `factories.py`.
- `backend/app/models/` mirrors the hand-written Alembic schema; it does not
  generate migrations.
- `backend/app/workers/` owns sync RQ entry points and async bridging.
- Frontend dependency direction is `atomic-crm` → `admin` → `ui`; product code
  belongs in `frontend/src/components/atomic-crm/`.
- Avoid circular imports and raw SQL. Keep all I/O async; offload blocking crypto.

## Implementation rules

- Read relevant docs and 2–3 neighboring files before editing.
- Prove a bug's cause before changing behavior; add a regression test.
- Prefer YAGNI, then KISS, then DRY. Make small, focused changes.
- Preserve public contracts unless the approved scope changes them.
- Backend: Pydantic v2, SQLAlchemy 2.x `select()`, domain errors mapped by API.
- Frontend: strict TypeScript, no `any`, Vietnamese user-facing text, `cn()` for
  class composition, TanStack Query for server state, virtualized long lists.
- LLM calls go through `backend/app/graph/clients.py`; never call providers from
  services directly.
- Use structured logging; never `print()` or log secrets/PII.
- Never add fake production behavior, hide failing checks, or delete tests to
  make a suite pass.
- Preserve unrelated user changes in a dirty worktree.

## Protected operations — explicit approval required

Stop and ask before:

- creating or editing `backend/alembic/versions/*.py`;
- changing Zalo webhooks, OpenRouter/OAuth integrations, auth/JWT/CORS/rate-limit
  behavior, or other security-sensitive code;
- changing API response contracts or database schemas incompatibly;
- changing bot prompts, safety, grounding, or tool definitions;
- adding, removing, or upgrading dependencies;
- changing deployment files or executing a deployment;
- introducing a cross-cutting architecture pattern.

Never auto-edit secrets (`.env`, private keys, credentials) or weaken privacy or
signature-validation controls. Shared Claude hooks in `.claude/settings.json`
enforce the mechanically detectable subset; see `docs/agent-development-kit.md`.

Files requiring approval include:

- `.env`, `backend/.env` (never agent-edited)
- `backend/alembic/versions/*.py`
- `backend/docker-compose.yml`, `backend/Caddyfile`
- `backend/app/core/config.py`, `security.py`, `ratelimit.py`
- `backend/app/api/webhooks.py`, `dependencies.py`
- `backend/app/graph/prompts.py`, `safety.py`, `grounding.py`, `tools.py`,
  and persona prompt files
- `frontend/src/index.css`
- root/backend/frontend `Makefile`
- `backend/pyproject.toml`, frontend dependency manifests

## Workflow

1. Scout the repository and check `plans/` for conflicting in-flight work.
2. Clarify only choices that cannot be discovered locally. For broad or risky
   work, plan under `plans/<timestamp>-<slug>/`.
3. Implement using existing patterns and tests-first where practical.
4. Run the narrowest relevant check, then broaden for shared contracts.
5. Review security, performance, accessibility, error handling, compatibility,
   and documentation impact.
6. Update docs only for user-visible behavior, setup, commands, architecture,
   security posture, public contracts, or durable maintainer decisions.

Do not deploy, commit, push, merge, or open a PR unless the user asks for that
external state change.

## Git workflow

- Work directly on `main`. Do not create feature branches — commit all changes
  to `main`.

## Essential verification

Backend, from `backend/`:

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Frontend, from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test:unit:app
npm run build
```

Use focused files/keywords first. The full acceptance checklist lives in
`standards/definition-of-done.md`; manual dev QA lives in `docs/qa-runbook.md`.

## Task routing

- Implementation: use `.claude/skills/implement-change/SKILL.md` when available.
- Verification: use `.claude/skills/verify-change/SKILL.md` when available.
- Dev-environment QA: use `.claude/skills/qa-dev-environment/SKILL.md`; record
  findings without auto-fixing them.
- Bot diagnosis: use `docs/troubleshooting/chatbot-response-path.html` and the
  relevant project expertise under `.omc/skills/` when locally available.
- Deployment: read `docs/deployment-guide.md` in full and obtain approval first.
