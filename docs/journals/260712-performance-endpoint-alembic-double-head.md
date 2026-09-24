---
title: "Performance endpoint — alembic double-head fork that the test suite cannot see"
date: "2026-07-12"
status: resolved
scope: "backend/app/api/performance.py, alembic 0031-0033, tests/test_performance_endpoint.py"
---

# Performance endpoint — alembic double-head fork that the test suite cannot see

Plan: `plans/2026-07-12-performance-endpoint-latency/plan.md` (directory removed
after the work shipped — see git history).
Commits: `c415e76c` (migration renumber, made outside the session) and `208c8ad3`
(this session: `asyncio.gather` parallel reads + 30s Redis cache).

## What shipped

Three changes to the `GET /api/v1/admin/performance?window=24h` recruiter
dashboard. (Brief — the commit message and plan cover this.)

- **Migration `0033_bot_runs_started_at_index`** — standalone B-tree on
  `bot_runs (started_at DESC)`. The existing composite indexes
  `(conversation_id, started_at DESC)` and `(outcome, started_at DESC)` had a
  wrong leading column for a `started_at`-only range predicate, so Postgres
  fell back to Seq Scan on five time-windowed queries. Also corrects a stale
  claim in migration `0027` that those indexes "bound the time-window scans."
- **Parallelized the reads** — the 5 DB reads + queue health now run via
  `asyncio.gather`, each on its own `AsyncSession` (AsyncSession is not safe
  for concurrent use). Cuts DB wall-time from `sum(queries)` to ~`max(queries)`.
- **30s Redis response cache** — key `perf:dashboard:{window}`, TTL matches
  the frontend `staleTime`. Auth runs before cache lookup; cache failures fall
  through to compute. On a cache hit the real-time queue-depth tile is up to
  30s stale — documented in the module docstring; acceptable for a trends view.

## The event that matters: a double-head alembic fork

The plan's own Session-1 validation had **explicitly anticipated and
"prevented"** this exact failure — it renumbered the new migration `0031→0032`
to avoid forking the chain. I trusted that. False security.

Between plan-validation and implementation, a *different* uncommitted
migration `0032_bot_run_outcome_metadata.py` landed in parallel. Both that
file and my new migration carried `down_revision = "0031_conversation_seq_trace"`.
Two children of the same parent → **the alembic tree forked into two heads.**
`alembic upgrade head` in production would have died with
`Multiple heads are present; please specify which head.`

**The mandatory `code-reviewer` subagent caught this. The test suite did not.**

That is the whole point. The pytest suite is 689 tests across 65+ files and
runs green. It exercises zero of the alembic migration graph, because the
conftest test schema is built from metadata, not by running migrations. A
green CI run gave confidence that was structurally unfounded. This is the
exact same class of blindness as the Zalo webhook journal from earlier today
("672 backend tests green while three prod bugs were live") — the suite
passes because it cannot observe the failure surface.

Fix: renumber to `0033` chaining after `0032_bot_run_outcome_metadata`
(commit `c415e76c`). Chain is now linear: `0030 → 0031 → 0032 → 0033`.

## The brutal truth

The plan-validation step is theatre if the world it validated against has
moved by implementation time. I treated "we already renumbered to avoid the
fork" as a closed item. It was a closed item against a snapshot that no
longer existed. The fork was introduced *after* validation, by someone else's
uncommitted file, and the only thing standing between it and a broken prod
deploy was a subagent I am required to run. If `code-reviewer` had been
optional that day, this would have shipped.

## Secondary lessons

1. **Plan-vs-reality drift on query count.** The plan was written against 4 DB
   reads; a `_reliability` query (joining `messages` to `bot_runs`) had been
   added since, making it 5. The plan's "4" was stale at implementation time.
   Always re-scout the actual current code even when executing a validated
   plan — don't trust the plan's line counts blindly.
2. **A sequential test stub cannot validate concurrency.** The original test
   used a queue-based fake (`results.pop(0)`). That stub passes whether the
   code is sequential OR gathered — it cannot distinguish them. The new
   concurrency test asserts `max_inflight >= 2` via `asyncio.sleep(0)` yields,
   and genuinely fails if reads go sequential. Concurrency tests need fakes
   that can observe scheduling, not just sequence.
3. **Migration revision-id ≠ filename.** `0031_conversation_seq_and_trace_id.py`
   carries `revision = "0031_conversation_seq_trace"` — no `_and`. Every
   `down_revision` must match the revision *string*, not the filename. Easy to
   get wrong by eyeballing filenames; I verified all four `down_revision`
   strings against the actual `revision =` lines before trusting the chain.
4. **Cache-hit `live` tile staleness is a real semantic tradeoff.** On a cache
   hit, `collect_queue_health()` doesn't run, so the one explicitly-real-time
   field is up to 30s stale. Acceptable (matches the frontend's existing 30s
   treatment of the whole payload), but it is a behavior change, not just an
   optimization. Documented in the module docstring so the next person doesn't
   have to rediscover it.

## Lesson I am not allowed to forget

**Alembic head-count is a CI gap.** A one-line assertion in CI —
`alembic heads` must print exactly one line, else fail — catches this whole
class of fork automatically, in milliseconds, with no human reviewer in the
loop. The test suite passing green is not evidence the migration graph is
linear, because the suite does not run migrations. Reviewers catch it; CI
should too.

## Verification

- `test_performance_endpoint.py`: 10/10 pass (was 4 — added cache hit/miss/
  fall-through/falsy/key-order + the falsifiable concurrency test).
- Full backend suite: 689 passed, 2 pre-existing unrelated failures (missing
  `docx` / `openpyxl` optional deps).
- ruff clean; frontend typecheck + lint clean.
- `alembic heads` → single head.

## Next

- Add `alembic heads` count == 1 as a CI gate. Owner: whoever touches CI next.
  This is the highest-value follow-up from this session.
- When a plan references specific line counts or query counts, re-verify them
  against current source at implementation time, not at plan-validation time.
- Treat any "we already handled X" item in a plan as a hypothesis to re-check,
  not a closed ticket — especially when the failure mode (migration fork) is
  invisible to the test suite that "validated" the plan.
