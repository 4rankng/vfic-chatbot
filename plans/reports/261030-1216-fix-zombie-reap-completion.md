# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

Restored 2026-09-27 (DOC-19) after `65069078` deleted it. The 2026-09-27 sweep
had to reconstruct these sixteen gates from the previous sweep's report because
this file was gone; the gate list is meant to live here, not in the most recent
report. Do not renumber or drop gates when filling one in — a report that omits a
gate is a report that was not filled from this file.

## Task record

- Task: Fix zombie-process accumulation in the RQ worker containers on
  bot.tingting.vip (`ps -eo stat | grep Z` climbing 15 → 22 → 29 across the
  day; host load inflated on the 2-core droplet) — reap child processes
  without changing job behavior.
- Scope: worker-entry child reaping (SIGCHLD handler with a paused work-horse
  cycle for RQ's fork worker), compose launch commands for the fork-worker
  services, regression tests, doc updates. Excluded by instruction: deploy,
  Telegram, worker-class changes, job-code changes.
- Files changed: `backend/app/workers/child_reaper.py` (new),
  `backend/app/workers/reaping_worker.py` (new),
  `backend/app/workers/run_worker.py`, `backend/docker-compose.yml`,
  `backend/tests/test_child_reaper.py` (new),
  `docs/architecture/system-architecture.md`,
  `docs/product/codebase-summary.md`, this record.
- Instructions retrieved: the task brief (inline). Routing named skill
  `chatbot-integrations` — not present in the skill registry or the repo's
  `.claude/skills`; its one stated pitfall ("RQ worker pattern là đường duy
  nhất") was followed: the fix is expressed inside the RQ worker pattern
  (`run_worker.py` + an `rq.Worker` subclass), no parallel mechanism.
  `skill://itsaplan-board` read for the board protocol.
- Approval required: yes — deployment-file change (`docker-compose.yml` worker
  commands).
- Approval evidence: the task brief orders the fix, commit and push explicitly
  ("IMPORTANT: fix ticket được giao, commit + push. Không hỏi.") and prescribes
  the SIGCHLD-handler/worker-settings fix class; no deploy performed.

## Root-cause evidence (pre-fix investigation)

- Reproduced locally against a throwaway redis: stock `rq worker` (fork) ran
  30 jobs → 0 zombies at every 1s sample — RQ 2.10 reaps its own work horse
  (`os.wait4(self.horse_pid, 0)`), so "rq fork per job mà không wait" is
  disproven as the whole story.
- Exhaustive scan of `backend/app` + `backend/scripts` + `scripts/`: zero
  `subprocess`/`Popen`/`os.system`/`os.fork`/`multiprocessing` call sites in
  job code; the only spawn-adjacent code is test tooling.
- Prod topology: every vfic container runs `docker-init` (tini) as PID 1, so
  orphaned grandchildren are reaped; the workers' own Python processes are the
  only long-lived parents that can hold a zombie alive. Both RQ worker classes
  only ever wait for children RQ knows about (`wait4(horse_pid)` or nothing),
  so ANY child that exits un-waited inside a worker process is a permanent
  zombie — the accumulation mechanism the fix closes.
- Live watch on the droplet (zombie + per-worker child sampling, ~50 min after
  the 03:12 container recreate): 0 zombies, worker children empty — the leak
  is episodic (incident samples were 15/22/29 over a day), so its exact
  species was not captured live; the fix removes the in-repo accumulation path
  regardless of which child dies.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Reaper installed in both worker entries (`run_worker.main`, `ReapingWorker.__init__`); fork entry wired in compose (`--worker-class app.workers.reaping_worker.ReapingWorker`). Smoke on real entries: fork worker burst 3/3 `Job OK`, `status=finished`; `run_worker persistence_low` 3/3 `Job OK`; host zombie count 0 at every sample of both runs. |
| Diff is limited to the approved scope | PASS | 8 files: 3 worker code, 1 compose, 1 test, 2 docs, 1 record. No job-code, worker-class (SimpleWorker/fork split preserved), or unrelated change. |
| Protected operations were avoided or approved | PASS | No deploy, no Telegram, no branch/PR ops. Commit+push performed only as ordered in the brief. |
| Focused tests/checks pass | PASS | `pytest tests/test_child_reaper.py` 4 passed (run twice, deterministic): un-waited children stay zombies (bug guard), `install()` reaps backlog + live children (stat Z count → 0), paused horse cycle keeps the horse's exit status for RQ's `os.wait4` and sweeps deferred zombies at `resume()`. Related suites: 31 passed (`test_logging_credentials`, `test_compose_service_contracts`, `test_worker_warm_start`, `test_worker_enqueue_utils`). |
| Broader regression tests pass when shared behavior changed | PASS | Repo gate invocation `pytest -q -m "not integration" --cov --cov-config=.coveragerc`: 4185 passed, 28 skipped, 0 failed, coverage TOTAL 81.5% (floor 75). 3 errors are the integration lane requiring the local pgvector dev service (`docker compose -f docker-compose.dev.yml up -d postgres`) — environmental, unrelated to this diff. |
| Lint passes for affected code | PASS | `ruff check app/workers/ tests/test_child_reaper.py` → All checks passed. |
| Type checking passes for affected code | PASS | `uvx pyright --pythonpath <venv> app/workers/child_reaper.py app/workers/reaping_worker.py` → 0 errors, 0 warnings (the repo gate's pyright scope is `app/graph`; extended to the affected files). |
| Build/import validation passes for affected code | PASS | `import app.workers.reaping_worker` resolves; both entries ran real jobs end-to-end (see the first gate). `backend/Dockerfile` installs the package (`pip install --no-deps -e .`), so `--worker-class app.workers.reaping_worker.ReapingWorker` resolves container-wide in prod. |
| Security and privacy impact reviewed | PASS | No secrets/PII touched or logged (reaper logs pid numbers at DEBUG). `test_no_container_argv_element_is_a_credential_value` green — the new argv elements are not credentials. |
| Performance and async-I/O impact reviewed | PASS | SIGCHLD handler only performs non-blocking `os.waitpid(-1, WNOHANG)` reaping; the horse cycle does O(1) pause/resume bookkeeping; job execution path byte-identical (stock `rq.Worker.execute_job` inside). |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | `ChildProcessError` handled in `sweep()`; RQ's tolerated fallback verified in rq 2.10 source (`wait_for_horse` suppresses `ChildProcessError`, `monitor_work_horse` falls through to the job status in Redis — a finished job still reports success). Portable: no `/proc`, no `os.waitid` (tests use `ps -o stat=`, works on macOS dev + Linux CI). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/architecture/system-architecture.md` (worker entrypoint bullet) and `docs/product/codebase-summary.md` (workers tree) updated; `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Diff grep: none added. |
| Final `git diff --check` passes | PASS | `git diff --check` clean. |
| Final `git status --short` reviewed | PASS | Exactly the 8 scoped files (3 new, 5 modified). |

## Result

- Overall status: PASS.
- Remaining risks or follow-ups:
  1. The exact zombie species in prod was never captured live (watchers saw
     none in the ~50 min after the incident-day recreate; the leak is
     episodic). If zombies ever recur with parents OUTSIDE the worker
     processes (e.g. containerd-shim from `docker exec` healthchecks), that is
     an infra-level reaping issue beyond this repo's surface.
  2. `app/workers/reaping_worker.py` is covered by the smoke runs, not by unit
     tests (it is 14 statements of delegation around `rq.Worker.execute_job`;
     the reaper invariants it wires are unit-tested in `test_child_reaper.py`).
  3. The integration lane needs the local pgvector dev service to run its
     3 remaining tests.
