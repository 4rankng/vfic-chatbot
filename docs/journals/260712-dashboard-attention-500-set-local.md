---
title: "Dashboard /attention 500 — SET LOCAL on a shared request session"
date: "2026-07-12"
status: resolved
scope: "backend/app/services/dashboard/service.py, backend/tests/test_dashboard_attention.py"
---

# Dashboard /attention 500 — SET LOCAL on a shared request session

## What happened

`GET /api/v1/dashboard/attention` returned HTTP 500 in production
(bot.tingting.vip) with:

```
asyncpg.exceptions.ActiveSQLTransactionError:
  SET TRANSACTION ISOLATION LEVEL must be called before any query
```

Traceback key frames:

```
File "/app/app/api/dashboard.py", line 27, in attention
    return await DashboardService(db).attention(user)
File "/app/app/services/dashboard/service.py", line 164, in attention
    await self.db.execute(text("SET LOCAL transaction_isolation = 'repeatable read'"))
```

This is the third entry today about a failure class the unit suite
structurally cannot see (see `260712-zalo-oa-webhook-user-resolution.md`
and `260712-performance-endpoint-alembic-double-head.md`). Same shape,
different surface.

## Root cause (exact)

`DashboardService.attention()` runs `SET LOCAL transaction_isolation =
'repeatable read'` so the 3 sequential reads see a consistent snapshot.
Postgres requires that statement to be the FIRST in its transaction.

But the FastAPI auth dependency `get_current_user`
(`app/api/dependencies.py:41`) had already autobegun a transaction on
the SAME shared request `AsyncSession` — `get_db` yields one session for
the whole request (`app/core/db.py:27-34`) — by running
`await db.get(User, user_id)` to load the viewer from the JWT. So
asyncpg correctly rejected the `SET LOCAL` as "not first."

The fault is not in `get_current_user` and not in the dashboard service
in isolation. The fault is the **composition**: a shared request-scoped
session plus an auth dependency that always issues a SELECT first,
guaranteeing the transaction is open before any handler line runs.

## Why tests missed it

`tests/test_dashboard_attention.py` faked the session with
`SimpleNamespace(execute=AsyncMock())`. No real transaction state, so
`ActiveSQLTransactionError` never fired. Pure-unit mocks cannot catch
"this SQL statement must be the first in a transaction" — that is a
property of the server's transaction state machine, which the mock does
not model.

Same meta-lesson as the zalo and alembic entries: a green unit suite is
not evidence the production contract holds. The suite passed because it
could not observe the failure surface, not because the code was right.

## Fix (minimal, root-cause)

Added `await self.db.rollback()` immediately before the `SET LOCAL` in
`service.py`. This ends the autobegun read-only transaction so
`SET LOCAL` becomes the first statement of a fresh transaction, which
then inherits REPEATABLE READ for the 3 repo reads.

The rollback is safe because: (a) the viewer object is already fully
loaded above it, and (b) the repo uses raw SQL with no identity-map
dependency that the rollback could invalidate. Comment block updated to
explain why the rollback is load-bearing, not incidental.

## Verification

- 28/28 dashboard tests pass, including the new regression test
  `test_rolls_back_prior_transaction_before_set_local`, proven to fail
  without the fix and pass with it.
- 726/728 full suite passes. The 2 failures
  (`test_extract_text_docx`, `test_extract_text_xlsx`) are pre-existing
  missing-optional-deps (`docx`, `openpyxl`), confirmed failing on
  `main` before this fix.
- `ruff check` clean; `ruff format --check` clean.
- Blast radius: only `/dashboard/attention` uses `SET LOCAL`. Sibling
  `metrics()` and no other endpoint in the codebase uses this pattern.

## The generalized lesson (the important part)

A whole class of Postgres statements that must be first-in-transaction
will hit this same shared-session-dependency pattern:

- `SET TRANSACTION ISOLATION LEVEL`
- `SET CONSTRAINTS`
- `SET LOCK_TIMEOUT` / `SET STATEMENT_TIMEOUT` (when issued as
  transaction-local)
- `SET SESSION AUTHORIZATION`
- `BEGIN`

Every one of them is doomed on a request-scoped `AsyncSession` in this
codebase, because EVERY authenticated route shares one session and
`get_current_user` always runs a SELECT first. The transaction is
already open by the time any handler line executes.

**Defensive rule:** any `SET ...` statement issued on a request-scoped
`AsyncSession` must assume an upstream dependency already opened the
transaction. Either roll back first (what we did here), use a fresh
connection, or move the setting to session level (`SET` without `LOCAL`,
or a per-role/per-database default) so ordering no longer matters.

This trap is structurally invisible to pure-unit tests. It needs an
integration test against a real Postgres transaction — the same gap
called out in the alembic entry. The two are the same gap.

## The brutal truth

I added `SET LOCAL transaction_isolation` to get snapshot consistency
across 3 reads and wrote a clean-looking unit test with a mocked
session. The test passed. The code shipped. Production 500'd on the
first real request because the very first thing every authenticated
request does — load the viewer — opens the transaction my `SET LOCAL`
needed to lead.

The maddening part is that I already knew the dependency shape: I wrote
the regression test for the alembic concurrency bug this morning using
the same insight ("the test fake cannot observe the real failure
surface"). And I still shipped a dashboard read path with no integration
coverage against a real transaction. The lesson keeps trying to land
and I keep giving it new places to bite.

## Next

- Treat any new `SET ...` on a request-scoped `AsyncSession` as a
  review red flag: does it roll back first, or is it doomed? Add this to
  the same CI gate list proposed in the alembic entry.
- Add at least one integration test (real Postgres transaction, real
  auth dependency chain) for `/dashboard/attention` so the
  first-in-transaction contract is exercised, not just asserted by a
  mock.
- Audit sibling endpoints for any other `SET LOCAL` / `BEGIN` usage on
  the shared session — confirmed clean today, but cheap to re-check on
  touch.
