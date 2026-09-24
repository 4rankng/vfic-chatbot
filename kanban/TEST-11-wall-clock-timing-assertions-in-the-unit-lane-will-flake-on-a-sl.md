---
id: TEST-11
title: "Wall-clock timing assertions in the unit lane will flake on a slow runner"
severity: medium
area: testing
labels: [testing]
effort: M
status: todo
found: 2026-09-24
---

# TEST-11 — Wall-clock timing assertions in the unit lane will flake on a slow runner

**Severity:** medium · **Area:** testing · **Effort:** M · **Labels:** testing

## Problem

Several unit tests prove concurrency or deadline behaviour with narrow wall-clock margins, so a GC pause or scheduler delay on a shared runner makes them red while the code is correct. The unit lane also has a 20-minute budget and no per-test timeout, so a genuine hang consumes the whole budget with no signal.

## Evidence

- `backend/tests/test_parallel_tools.py:594-622` — two 50 ms sleeps then `assert elapsed_ms < 90, f"prefetch was sequential ({elapsed_ms:.0f}ms >= 90ms)"`; the comment states the intent is to prove `gather()` is used.
- `backend/tests/test_turn_deadlines.py:53-56` uses `pytest.approx(1.2, abs=0.05)`, `:64-72` asserts `4.9 < d.remaining("unknown_stage") <= 5.0`, and `:80` uses `pytest.approx(time.time() + 3, abs=0.1)`.
- `backend/tests/test_graph_runner_turn.py:1197-1216` — `await asyncio.sleep(0.8)` then `assert zalo.actions.count("typing") >= 1` against a ~0.5 s heartbeat, a 0.3 s margin; `:693` sets `deadline_at_epoch = time.time() + 0.5`.
- `backend/tests/test_parallel_tools.py:137` sleeps 0.3 s, and `.github/workflows/quality-gates.yml:20` gives `backend-unit` `timeout-minutes: 20` with no `pytest-timeout` in `backend/pyproject.toml:60-67`.

## Impact

A red on a slow runner costs a re-run, and a real hang consumes the entire 20-minute job budget without identifying the offending test.

## Suggested fix

Replace wall-clock proofs with the concurrency-counter form the suite already uses correctly (`test_parallel_tools.py:637-663` asserts `max_active == 1`), or inject a captured sleep list as `test_graph_decisions.py:317-321` does. Widen the remaining budget assertions to non-flaking bounds (`abs=0.15`) or freeze the clock, and add `pytest-timeout` with a per-test cap.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
