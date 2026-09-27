# Definition of Done

> A task is complete only when ALL of the following are true.
> This is the completion gate — no exceptions.
> Also see [`review-checklist.md`](review-checklist.md) for the detailed pre-submit checklist.

Restored 2026-09-27 (DOC-19) after `65069078` deleted it. The pointer to a
separate `performance.md` and `security.md` was dropped: those files were
deleted with this one and their content now lives in the documents named below.

## Completion Gate

A task is **Done** when every item below is verified:

```
Build passes
    ↓
All tests pass
    ↓
No lint errors
    ↓
No type errors
    ↓
Documentation updated
    ↓
No TODOs without linked issues
    ↓
Migration reviewed (if any)
    ↓
Performance checked
    ↓
Security reviewed
    ↓
Agent routing still resolves (if it changed)
    ↓
DONE
```

## Checklist

### 1. Build passes
- Backend: `python -c "import app.main"` succeeds (no import errors, no circular imports)
- Frontend: `npm run build` succeeds (from `frontend/`)

### 2. All tests pass
- Backend: `.venv/bin/pytest` (from `backend/`) — all unit tests pass. The suite is
  pure unit; the DB-backed lane is `-m integration` and is a manual lane, not a
  deploy blocker.
- Frontend: `npm run test:unit:app` (from `frontend/`) — all vitest app-project tests pass
- If you touched a shared contract, run tests in modules that depend on it — not just the module you changed

### 3. No lint errors
- Backend: `.venv/bin/ruff check .` (from `backend/`)
- Frontend: `npm run lint` (from `frontend/`)

### 4. No type errors
- Frontend: `npm run typecheck` (from `frontend/`) — `tsc --noEmit`
- Backend: Python type hints are advisory but should be consistent

### 5. Documentation updated
- If behavior changed, update the relevant doc in `docs/`
- If a new endpoint was added, update [`docs/architecture/api.md`](../docs/architecture/api.md)
- If a new architectural decision was made, add an ADR in [`docs/decisions/`](../docs/decisions/)
- If a coding pattern changed, update [`docs/development/code-standards.md`](../docs/development/code-standards.md)

### 6. No TODOs without linked issues
- New `TODO` / `FIXME` / `HACK` comments must reference an issue: `# TODO(#123): ...`
- Remove TODOs that were resolved by this change

### 7. Migration reviewed (if any)
- Migration is hand-written (not auto-generated)
- Tested locally: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`
- Reversible (downgrade path works)
- No data loss without explicit documentation and approval
- Production backed up before deploy: `make backup`
- The single Alembic head still matches the `**HEAD:**` line in
  [`docs/ops/deployment-guide.md`](../docs/ops/deployment-guide.md) — the release
  gate greps for it

### 8. Performance checked
- No new N+1 queries (use `selectinload` / `joinedload`)
- No blocking I/O on the async event loop
- Long lists virtualized with `virtua` (`VList`)
- LLM calls respect the concurrency semaphore
- Targets and observability: [`docs/product/overview-pdr.md`](../docs/product/overview-pdr.md)
  and [`docs/architecture/system-architecture.md`](../docs/architecture/system-architecture.md)

### 9. Security reviewed
- No secrets logged
- Auth enforced on all non-public endpoints (`get_current_user`, `require_admin`, `require_recruiter`)
- Input validated
- Webhook HMAC intact (if touching `webhooks.py`)
- Boot-time safety rules and credential handling are unchanged — see
  [`docs/development/code-standards.md`](../docs/development/code-standards.md)
  and [`docs/ops/incident-runbook.md`](../docs/ops/incident-runbook.md)

### 10. Agent routing still resolves
- If you added, moved, renamed, or deleted anything this repository's agents are
  routed to, run `node scripts/check-doc-links.mjs` from the repo root. It fails
  when a routed path or `make` target named in `.claude/CLAUDE.md`, `AGENTS.md`,
  or this directory no longer exists. The root `Makefile` `release-check` gate
  runs it.

## What "Done" is NOT

- ❌ "It works on my machine"
- ❌ "The tests should pass" (run them — fresh evidence required)
- ❌ "I'll add tests later"
- ❌ "The lint errors are pre-existing" (fix them or document why they're out of scope)
- ❌ "Documentation can be added in a follow-up PR"
- ❌ "It's just a small change, no need to check performance/security"

Every item above must be verified with fresh evidence before declaring done.
