# Sweep-gate — the release gate ticket closed

## Outcome

The release gate ticket is closed at HEAD `e5841446`. Of the four elements the
ticket's suggested fix named, today's earlier commits had already covered
none of the remaining three code elements, so the changeset that landed
tonight is the whole remainder: the gate rename, the CI turn smoke, the
release-check CI-green requirement, and the latency-is-not-gated-in-CI
documentation. I verified every element against current HEAD before anything
was committed, proved the new CI smoke steps end to end against a disposable
database, and committed the docs trail.

## What the ticket asked

TEST-04 (the release gate is real but narrow, mislabelled correctness, and not
wired to deploy) had four asks in its suggested fix: rename the golden gate
`correctness` → `retrieval_correctness` in `release_gate.py` and its failure
detail; run `scripts/smoke_turn.py` in CI against a stubbed provider; make
`release-check` require a green CI run for the exact commit under release; and
either enable the latency SLO in CI or document that latency is not
release-gated. The ticket's Notes section explicitly scoped OUT the turn
pipeline itself (2,464 lines of behaviour tests already prove it) — the gap
was that no CI gate ran any of it.

## What today's commits already covered

The lead's brief listed four landings as possibly covering ticket elements; I
checked each against the ticket's asks and none covered the remainder.

- `5f8e2378` ran the full `-m integration` suite in release-check and CI
  (harness smoke as fast-fail canary, then all 29 files with `--durations=25`,
  job timeout 20→45m). Real coverage, but it gates the pytest suite, not a
  bot turn — the ticket's Notes name `scripts/smoke_turn.py` as the right
  pre-flip shape and say the gap is that "no CI gate runs any of it". The
  pytest integration lane and the smoke script overlap in services but not in
  surface, so the CI smoke element genuinely remained.
- `feb38b13` added the deployment-guide-vs-`alembic heads` assertion to both
  release-check and CI. Unrelated to any of the four asks.
- `e16cee6c` wired the backend coverage gate into CI. Unrelated to the four
  asks.
- `1e466bb5` added pytest-timeout hang guards. Unrelated to the four asks.

So the entire remainder — rename, CI smoke, Makefile wiring, latency docs —
was still open when my lane started.

## The concurrent writer

Minutes into my lane, uncommitted changes appeared in exactly my released file
set. File mtimes ran 22:01:05–22:02:44 across `release_gate.py`, both gate
test files, the workflow, and the Makefile — the content matched the ticket's
suggested fix one-for-one. I flagged it to the lead mid-session with the
evidence and stated my plan (verify, complete, commit); no answer arrived
before the writer committed the same content itself at 22:03:58 as three
commits: `daeed012` (rename), `75c27fd5` (CI smoke), `6e51bdf8` (Makefile).
No reply from the lead by lane end.

Because the commits are byte-identical to the working tree I had just
verified (the files showed clean in `git status` immediately after), my
verification stands for the committed state. I did not duplicate or rebase
anything; the docs trail was the only part the writer left uncommitted, so
that is the only commit carrying my name: `e5841446`.

## What landed, element by element

- **Rename** (`daeed012`): the gate label is `retrieval_correctness` in all
  three `GateFailure` constructions, the `not_evaluated` entry, and the
  docstring/comment; the missing-golden detail no longer says "release
  correctness run". The importer trail: `backend/tests/test_release_gate.py`
  (three pins: the regression-block pin, the not-evaluated set pin, the
  missing-golden pin) and `backend/tests/test_release_gate_cli.py` (the
  "disabled by settings" pin). `backend/scripts/release_gate_check.py` is
  intentionally untouched — its one user-facing message names the setting
  `release_gate_correctness_enabled`, which keeps its historical name (it is
  deployment surface; renaming it would be an API/config break the ticket
  never asked for), and the source comment added by the rename documents that
  split explicitly. A repo-wide grep finds no other old-label reference:
  the only remaining "correctness" strings are the setting name and unrelated
  prose about answer correctness in general docs.
- **CI turn smoke** (`75c27fd5`): the `release-gate` job now declares
  postgres+redis services (mirroring backend-integration), migrates a
  disposable database with `APP_ENV=development` (mirroring the integration
  conftest's `_run_alembic` env), runs `python -m scripts.smoke_turn` — one
  real turn through the real ConversationService/RetrievalRepository with LLM
  and Zalo stubbed — then runs the `--inject-failure` self-test and asserts it
  exits non-zero, so the gate must fail closed or CI goes red.
- **Makefile** (`6e51bdf8`): `release-check` now begins with two fail-closed
  lines: `gh` must exist, and `gh run list --workflow quality-gates.yml
  --commit "$(git rev-parse HEAD)" --status success --limit 1` must be
  non-empty. Missing gh, unpushed commit, no completed run, red run, cancelled
  run, or still-running pipeline all block with a pointed message — the
  deploy path can no longer proceed while CI is red, which was the ticket's
  core impact claim.
- **Latency SLO** (documented, in `75c27fd5` + `e5841446`): the workflow job
  carries a comment stating latency is deliberately not release-gated in CI
  (no 30-run telemetry window can exist there, synthetic seed telemetry is
  excluded by design), and the docs/testing.md release-gate row says the same.
  The ticket allowed enable-or-document; enabling in CI would be a no-op
  (empty DB → `not_evaluated`), so documentation is the honest half. This
  matches the sweep-final lane's note that enabling-or-documenting "can follow
  separately" — it followed, in the same changeset.

## Verification

- Focused: `tests/test_release_gate.py`, `test_release_gate_cli.py`,
  `test_deployment_makefile.py` — 65 passed at committed HEAD.
- Full backend unit lane: 2,299 passed, 24 skipped, 2 failed — the two known
  frontend-boundary failures the lead's brief pre-declared from the FE
  session's untracked files; matches the 2,299 baseline.
- `make -n release-check` parses (rc=0).
- Workflow YAML parses (`yaml.safe_load`).
- ruff clean across `backend/`.
- End-to-end proof of the new CI steps, run locally against a throwaway
  database (`smoke_gate_verify_*`, created and dropped by me): create DB →
  `alembic upgrade head` with the conftest's env shape → `python -m
  scripts.smoke_turn` exited 0 with `SMOKE OK: outcome='sent'` →
  `--inject-failure` exited 1 with the injected `record_bot_outcome` kwarg
  drift, exactly the outage class the smoke gate exists to catch. Throwaway DB
  dropped; nothing left behind.

## Residuals for the lead

- `backend/uv.lock` sits modified in the tree (adds the `coverage` package).
  It is not my lane's file and dependency manifests are protected; it looks
  like the coverage lane's lockfile sync that never got committed with
  `e16cee6c`. Needs an owner decision before the tree is truly quiet.
- `docs/testing.md`'s CI-jobs table has two stale rows outside my lane: the
  `backend-integration` row still says harness-smoke-only (stale since
  `5f8e2378` widened the lane) and it lists a `functional-e2e` job that does
  not exist in the workflow (the real job is `visual-e2e`). I fixed only the
  `release-gate` row I changed; those two rows need whoever owns the table.
- The concurrent writer never answered for itself and the lead had not
  replied by lane end; same anomaly sweep-final recorded. In this case the
  content was exactly my brief, so the harm was only process — but a lane
  that gets verified-and-committed underneath it is a real coordination
  hazard for future nights.

## Status

Status: DONE_WITH_CONCERNS
Summary: Release-gate ticket closed at `e5841446` — rename, CI turn smoke,
release-check CI-green requirement, and latency documentation all verified
(including an end-to-end smoke proof on a disposable database) and landed;
one docs commit of my own, three commits from the concurrent writer that I
verified byte-for-byte before they landed.
Concerns: (1) A concurrent writer authored and committed my lane's changeset
(the 22:01–22:04 window) without answering my mid-session flag or the lead's
reply; (2) `backend/uv.lock` is modified in the tree by another lane and
needs an owner; (3) two stale rows in docs/testing.md's CI-jobs table belong
to other lanes.
