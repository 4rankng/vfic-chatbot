# Review Checklist

> Reusable pre-submit checklist for every change. Run through this before declaring a task done.
> Also see [`definition-of-done.md`](definition-of-done.md) for the completion gate.

## How to Use

Before submitting any change (PR, commit, or agent-reported completion), verify every item below. If an item doesn't apply (e.g., no DB migration), mark it N/A.

---

## ✓ Security

- [ ] No secrets, API keys, tokens, or passwords in logs or code
- [ ] Auth enforced on all non-public endpoints (`get_current_user`, `require_admin`, `require_recruiter`)
- [ ] Input validated (Pydantic schemas on backend, form validation on frontend)
- [ ] Webhook HMAC validation intact (if touching `webhooks.py`)
- [ ] No new CORS origins without review
- [ ] No `eval()`, `exec()`, or `subprocess` with user input
- [ ] SQL parameterized (no string interpolation in queries)
- [ ] No new dependencies with known vulnerabilities

## ✓ Performance

- [ ] No N+1 queries (eager-load relations with `selectinload` / `joinedload`)
- [ ] No blocking I/O on the async event loop (crypto on `asyncio.to_thread`)
- [ ] Long lists virtualized with `react-virtuoso`
- [ ] No unbounded loops
- [ ] LLM calls respect the concurrency semaphore
- [ ] No new DB queries without appropriate indexes
- [ ] Frontend bundle size hasn't regressed (check `npm run build:analyze` if unsure)

## ✓ Accessibility

- [ ] Semantic HTML (`<nav>`, `<main>`, `<button>`) — not `<div>` with click handlers
- [ ] ARIA labels for icon-only buttons
- [ ] Keyboard navigation works (tab order, focus rings visible)
- [ ] Color contrast meets WCAG 2.2 AA
- [ ] Touch targets ≥ 44×44px (mobile)

## ✓ Logging

- [ ] Structured logs (via `app/core/logging.py`), not `print()`
- [ ] No PII in logs (emails, phone numbers, message content)
- [ ] Appropriate log levels (INFO for normal ops, WARNING for degraded, ERROR for failures)
- [ ] No excessive logging in hot paths (per-message loops)

## ✓ Tests

- [ ] New code has tests (backend: pytest, frontend: vitest)
- [ ] Existing tests still pass (`.venv/bin/pytest`, `npm run test:unit:app`)
- [ ] Edge cases covered (empty input, null, boundary values, error paths)
- [ ] Tests are pure unit (backend: fakes/mocks, no live DB/Redis/LLM)

## ✓ Error Handling

- [ ] Services raise domain errors (`NotFoundError`, `ConflictError`, `ForbiddenError`, `UpstreamError`)
- [ ] API layer catches domain errors and maps to `HTTPException` (404/409/403/502)
- [ ] User-facing error messages in Vietnamese
- [ ] No swallowed exceptions (empty `except:` blocks)
- [ ] Async tasks handle cancellation gracefully

## ✓ Documentation

- [ ] Updated if behavior changed
- [ ] API docs reflect new/changed endpoints
- [ ] No stale comments or TODOs without linked issues
- [ ] ADR created for architectural decisions (see [`../docs/decisions/`](../docs/decisions/))

## ✓ Backward Compatibility

- [ ] Public API contracts unchanged (response shapes, status codes) unless intentional
- [ ] Pydantic schema changes are additive (new fields optional) or breaking-change documented
- [ ] DB schema changes are backward-compatible or migration handles the transition
- [ ] Frontend route changes include redirects for old paths

## ✓ Database Migration Safety

- [ ] Migration is hand-written (not auto-generated)
- [ ] Tested locally (`alembic upgrade head` + `alembic downgrade -1`)
- [ ] Reversible (downgrade path works)
- [ ] No data loss (or data loss is explicitly documented and approved)
- [ ] No long-running locks on production tables (use `op.add_column` with `server_default` for non-null columns)
- [ ] Production backed up before deploy (`make backup`)

## ✓ Mobile Responsiveness

- [ ] Works on mobile viewport (test at 375px width)
- [ ] Bottom navigation functional
- [ ] Safe-area insets respected (`env(safe-area-inset-bottom)`)
- [ ] No horizontal overflow
- [ ] Touch targets ≥ 44×44px

## ✓ i18n

- [ ] All user-facing strings in Vietnamese
- [ ] New strings added to `vietnameseCrmMessages.ts`
- [ ] No hardcoded English in user-facing components
- [ ] Error messages use `friendlyApiMessage` (Vietnamese)

## ✓ Lint / Type Check

- [ ] `.venv/bin/ruff check .` passes (backend)
- [ ] `npm run lint` passes (frontend)
- [ ] `npm run typecheck` passes (frontend)
- [ ] `npm run build` succeeds (frontend)
