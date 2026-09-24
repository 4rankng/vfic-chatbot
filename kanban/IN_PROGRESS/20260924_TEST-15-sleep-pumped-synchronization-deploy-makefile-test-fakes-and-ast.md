---
id: TEST-15
title: "Sleep-pumped synchronization, deploy-Makefile test fakes, and AST-structure pins"
severity: low
area: testing
labels: [testing, tech-debt]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# TEST-15 — Sleep-pumped synchronization, deploy-Makefile test fakes, and AST-structure pins

**Severity:** low · **Area:** testing · **Effort:** S · **Labels:** testing, tech-debt

**Trạng thái:** TODO

## Problem

Three low-severity patterns remain in the suite: `await asyncio.sleep(0)` used as a synchronization primitive for fire-and-forget tasks, deploy-Makefile tests that re-implement the `bash`/`curl`/`docker` toolchain as fakes that accept essentially any invocation, and AST-structure pins that constrain code shape rather than behaviour.

## Evidence

- `backend/tests/test_concurrency.py:425-426` — two `await asyncio.sleep(0)` calls used to pump a fire-and-forget task before the assertion; the same pattern appears at `test_direct_turns.py:29-30`, `test_main_lifespan_cleanup.py:88`, `test_worker_async_runner.py:76,101,165` and `test_performance_endpoint.py:620`.
- `backend/tests/test_deployment_makefile.py:351-500` — `textwrap.dedent` fakes for `bash`, `curl` and `docker`; `:452-495` returns `raise SystemExit(0)` for essentially every docker invocation, so the test can detect only that some command ran, not that its shape is right.
- `backend/tests/test_webhooks.py:1060-1063` — parses `ZaloWebhookService.handle`'s source and walks it with parent tracking to assert "structural dominance"; `:1154-1157` strips docstrings via AST and scans the remaining code for provider names.

## Impact

The sleep-pumped assertions pass only because the event loop happens to schedule the task after N yields, so adding one `await` before its first real suspension fails the test for a reason unrelated to the invariant; the deploy fakes must be edited whenever `bg_deploy.sh` changes its tool usage; and the AST pins fail on a semantically equivalent early-return refactor.

## Suggested fix

Await the actual task handle or poll the module's task set explicitly — `test_concurrency.py:435` already asserts `events_mod._background_tasks == set()`, so use that as the wait condition. Keep the deploy ordering assertions (healthcheck → smoke → flip, abort-before-flip) and drop the parts that model tool behaviour, adding `shellcheck` on the scripts instead. Keep the provider-name leak scan at `test_webhooks.py:1154-1157` and replace the dominance pin with a behavioural assertion.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
