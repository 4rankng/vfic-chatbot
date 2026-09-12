# Suite Optimization Workflow (`optimize`)

Make the test suite and its CI cheaper and faster while keeping every safety
case covered. Optimize execution, never assertions: dropping real coverage to
save minutes is failure.

## 1. Parallel scout pass

Dispatch multiple parallel `ak:scout` subagents (one per area, disjoint scopes):

- **CI/CD workflows** — every pipeline file (`.github/workflows/`, etc.): job
  graph, triggers, matrices, caches, artifact flows, wall-clock and billable
  minutes per job (use `gh run list`/`gh run view` timings when available).
- **Git history** — mine the git history for which paths change together, change frequency per area,
  which tests fail most, which never fail (candidates for slimmer lanes).
- **Codebase** — module boundaries and the dependency edges that map source
  paths to the tests that exercise them.
- **Docs** — documented workflows whose coverage must never be dropped, plus
  pure-docs surfaces eligible for test skips.

Merge into one evidence report: cost per job, slowest tests, path→test-group
mapping, and safety-critical groups that must always run.

## 2. Optimization levers (apply in this order)

1. **Change-based test selection** — run only the test groups whose mapped
   source paths changed (derive the mapping from the dependency scout; keep a
   conservative fallback: unmapped changes run the full suite).
2. **Docs-only skip** — when a diff is docs-only (touches only documentation/prose surfaces),
   skip test execution in preflight/CI via path filters or a classifier gate;
   changes that touch both docs and code always run the code lanes.
3. **Parallel lanes** — split slow suites into balanced parallel jobs/shards;
   keep shards deterministic and isolation-safe.
4. **Cache and setup cost** — cache dependency stores and build outputs;
   hoist repeated setup into fixtures or shared jobs.
5. **Tiering** — fast smoke lane on every push; full suite on merge queues,
   protected branches, and risk-labeled diffs.
6. **Kill duplicate work** — deduplicate overlapping jobs, cancel superseded
   runs (concurrency groups), stop re-running unchanged matrices.

## 3. Safety gates (non-negotiable)

- Safety-critical groups (from the scout report) run on every code-touching
  diff regardless of change-based test selection.
- Selection/skip logic must fail open: classifier errors → run the full suite.
- Never weaken, delete, or skip an assertion to save time — that is `audit`
  territory, and only with evidence the test is worthless.
- Merge-blocking gates keep their trigger conditions; only their internal
  parallelism and selection change.

## 4. Apply and prove

- With `--interview`: list every proposed change (per workflow file, per test
  group) with expected savings and risk; interview the user per group; apply
  only approved changes. Otherwise apply directly and report the list.
- Prove no lost coverage: run the full suite once after restructuring; compare
  pass/fail sets and coverage totals before/after.
- Prove the savings: compare pipeline wall-clock/billable minutes on a real run
  (or a dry-run estimate per job) before/after.
- Report: levers applied, measured savings, safety groups preserved, fallback
  behavior, unresolved questions last.
