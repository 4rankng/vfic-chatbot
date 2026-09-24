# Sweep report — test-infrastructure lane

2026-09-24, lane sweep-tests, repo `/Volumes/LexarSSD/projects/chatbot`, branch `main`.

## Outcome

Ten commits landed across eight tickets. The knowledge-ingestion pipeline runs
its first live-DB tests in months, the stale-claim sweeps and the webhook
typing gate are proven by executed behavior instead of source text, tool/prefetch
concurrency is proven by observed overlap instead of wall-clock budgets, the
migration chain is walked end-to-end on every integration run (and immediately
found a real broken downgrade), backend coverage has a working config measuring
74.8% over `app`, and the frontend coverage gate now measures the whole
atomic-crm tree under a ratchet floor while keeping the strict 80% sub-gate on
the three hardening files. TEST-12's checkpointed guard was verified in place.
TEST-04, TEST-08, TEST-10 and TEST-14 are not delivered and are handed off with
implementation notes below. Full unit lane at handover: 3 failed, 2298 passed
(all three failures other lanes'; attribution below). Frontend: lint, typecheck,
598 unit tests and the coverage gate all green.

## Landed, by ticket

**TEST-02 (`2b22087d`, `ede78e7d`)** — The three modules behind unconditional
`pytest.mark.skip` were converted rather than re-marked: their still-live
behaviors run as `backend/tests/integration/test_knowledge_ingestion.py` (14
tests) against the disposable Postgres with the LLM/embedder seams faked.
Several parked tests encoded removed behavior — `KnowledgeStatus.APPROVED` is
now `PUBLISHED`, the feature catalog has 12 active features rather than 16,
digest failure falls back to deterministic source-grounded units instead of
raising `DigestError`, search and index visibility are gated on the
active-KB-version join — so the tests now pin current contracts, and the
approve/reject-API, drive-file-upload and multipart-endpoint tests were dropped
with the flows they pinned (the HTTP-level knowledge journey is TEST-14's e2e
spec). The unit-lane `_NoopRedis` double now tolerates the `nx=` kwarg real
callers pass so the integration lane runs under the shared conftest. Note: the
graph lane deleted `app/services/ingestion/` (with `fe565f9d`) including the
checkpoint's `test_fact_repository_active_release.py`; the TEST-09
fact-repository item is moot with it.

**TEST-12 (verified, no commit needed)** — The checkpoint's conftest guard
(`_block_external_http` in `backend/tests/conftest.py`) and
`test_unit_network_guard.py` (5 tests) are in place and passing; unstubbed
outbound HTTP and raw socket connects fail loudly with the offending host,
loopback and mock/ASGI transports stay allowed.

**TEST-07 (`93c0b10f`)** — The vitest `claude` project matched zero files and
exited non-zero when invoked. Project-level `passWithNoTests` does not change
the CLI exit code, and a top-level one would green an accidentally-empty app
project, so the dead project block is removed from `vitest.config.ts`. The
unused `test:unit:claude` script in `frontend/package.json` is now the only
remnant; whoever owns manifests should delete it.

**TEST-09 (`08f06b2c`)** — `create_pending_outbox` and `enqueue_outbox` are now
executed against a failing session stand-in, proving raise-vs-swallow by
behavior. The two claim-sweep AST pins were replaced by
`backend/tests/integration/test_outbox_stale_claim.py`, which seeds stale, fresh,
SENT and SEND_UNKNOWN outbox rows and asserts exactly which rows each sweep
touches. The worker entrypoint test executes `run_outbound_dispatch_tick` and
its delegation chain, keeping only the absence guards as source text. The
composition wiring pin in `test_outbox.py` stays (no unit-scope behavioral
substitute), and `test_logging_credentials.py`'s token pin is untouched — the
privacy hook gates that file for subagent reads and no user was available to
approve; its pin guards a real credential-leak incident and has no behavioral
substitute short of booting the RQ worker, so leaving it costs nothing.

**TEST-11 (`09d84f5d`)** — Both dual-dispatch proofs now observe scheduling
instead of racing clocks: in-flight counters prove both prefetch dispatches
overlapped, and start/finish timestamps prove the second tool started before the
first finished. The typing-heartbeat test drops its 0.8s wait because the
heartbeat pulses typing on its first scheduling slice (`next_typing` starts at
0), so a single yield orders the pulse before the answer. The checkpoint had
already removed `test_turn_deadlines.py` and `test_budget_and_paths.py` —
verified their subjects (TurnDeadline, the per-kind LLM budget) were deleted
from the app itself, so no coverage was lost. `pytest-timeout` remains
undeclared (dependency addition is approval-gated; hand-off below).

**TEST-15 (`d0cebd6d`)** — The webhooks AST dominance pin is replaced by
executing `handle()` for bot and OA channels and observing that only the bot
turn fires typing (the fire-and-forget recorder appends on its first event-loop
slice). The provider-name leak scan stays. The lifespan shutdown test's single
`sleep(0)` is kept but documented as a fixed cancellation-delivery point — I
tried replacing it with an event-driven wait and broke the test, which proves
the pump is load-bearing cancellation timing, not a flaky race. The
`test_worker_async_runner` child-task test now waits on a parent-started event.
The deploy-Makefile fake rework is handed off: the ops lane's Makefile work was
actively colliding with `test_deployment_makefile.py` (three of its tests were
red from ops commits mid-session and were fixed by ops), so I left the file
alone.

**TEST-03 (`18efd33d`)** — `backend/.coveragerc` (source `app`, tests and
alembic omitted, report-only with `fail_under = 0`) is verified working: the
unit lane measures 74.8% over 24,840 statements. pytest-cov is installed in the
local venv for verification only — declaring it in `pyproject.toml` is the
manifest owner's call. The frontend gate now includes all of
`src/components/atomic-crm/**` (measured 68.7 stmts / 58.1 branches / 59.5
funcs / 70.9 lines) under floors a few points below, so the CI number finally
covers the tree it claims to cover; the three hardening files keep per-file 80%
glob thresholds. Floors rise only. CI hand-offs: run `--cov` in the backend-unit
job once pytest-cov is declared, and relabel the frontend step (the script name
still says "changed-surface").

**TEST-05 (`60faf179`)** — `resource-paths.json` beside the dataProvider is the
single table; the frontend test drives the real provider against all eight
resources and asserts emitted URLs, and `backend/tests/test_frontend_api_contract.py`
asserts every table path is a GET route in the OpenAPI schema. All eight resolve
today, including the four aliased resources. The table ships as JSON with a
`?raw` import (declared in `vitest-browser.d.ts`) so it stays outside the
registry's publishable-source globs — a `.ts` table would trip the
registry-only-imported-by-tests rejection.

**TEST-13 (`68fb1934`)** —
`backend/tests/integration/test_migration_roundtrip_walk.py` walks the whole
chain (58 revisions at commit time) on a dedicated disposable database:
`upgrade <rev>` → `downgrade -1` → `upgrade <rev>`, finishing at head and
asserting a single head. Merge revisions skip the −1 step (two parents) and the
base skips it (nothing below). **First run found a real production-shaped bug**:
`downgrade 0003 → 0002` raises `psycopg.errors.InvalidTableDefinition: cannot
drop columns from view`. Fixing it is the ops lane's (OPS-16/17); until then
0003 is carried in `KNOWN_BROKEN_DOWNGRADES` as a self-expiring ratchet — when
fixed, the walk goes red until the entry is removed.

## Hand-offs and notes for other lanes

- **ops/manifest lane**: declare `pytest-cov` in `backend/pyproject.toml` dev
  extras and add `--cov --cov-config=.coveragerc --cov-report=term-missing` to
  the backend-unit CI job; the config is ready and measured 74.8%. Delete the
  `test:unit:claude` script from `frontend/package.json`. Fix migration 0003's
  downgrade (see TEST-13), then remove it from `KNOWN_BROKEN_DOWNGRADES`.
- **e2e/CI lane**: the visual projects (TEST-08) still need linux baselines via
  docker or honest removal, plus a CI job selecting them; relabel the frontend
  coverage CI step.
- **release-gate lane (TEST-04)**: everything lives in `backend/app/services/release_gate.py`
  (rename `correctness` → `retrieval_correctness`, then update
  `test_release_gate.py`/`test_release_gate_cli.py`), `.github/workflows/`
  (consume the gate, latency-SLO decision) and the Makefile's `release-check`;
  no honest test-lane work existed for me there.
- **TEST-10** (frontend raw-CSS assertions): the repo's own AGENTS.md pins the
  order — the remaining sheets need visual QA per screen, and the FE-19 card
  forbids batch rewrites. The highest-value conversions (touch targets, viewport
  overflow, hidden metadata) are renderable in the app vitest project; convert
  those per-file with per-file commits and delete the rest rather than re-pinning.
- **TEST-14** (e2e journeys): the harness (`backend/tests/e2e_harness.py`, my
  lane) seeds admin + one conversation with two messages; a knowledge journey
  needs a seeded project for the ProjectPicker, and a trace journey needs a
  seeded `bot_runs` row whose `decision_trace` JSON validates against
  `DecisionTrace` in `backend/app/schemas/bot_run.py` (`{"version": 2, "events":
  [{"seq": 1, "kind": "model_turn", "turn": 1, "phase": "final", "provider":
  "minimax", "model": "...", "reasoning_status": "not_returned", "tool_names":
  []}], "truncated": false}`); the Show page fetches `GET /api/v1/bot_runs/{id}`.
  Both journeys were scoped and designed but not delivered — see Concerns.

## Verification

Backend unit lane (after all commits): 2298 passed, 24 skipped, 3 failed — the
two `test_architecture_boundaries` browser-globals failures (frontend product
files, pre-existing before my first commit and owned by the FE lane) and
`test_model_tiering` (graph lane's template-lane removal; its own follow-up
`94ed3615` addresses it). Deployment-makefile and runtime-surface-inventory
failures that appeared mid-session from concurrent lane commits were fixed by
their lanes and are green again. Ruff clean on every touched file. Integration
lane, my files: knowledge-ingestion 14, stale-claim 3, walker 1 — all pass
against the live disposable DB (pytest-cov installed and later uninstalled/
reinstalled locally during verification; the venv is not a manifest). Frontend:
`npm run lint`, `npm run typecheck`, `npm run test:unit:app -- --run` (598
tests) and the coverage gate all green after my changes.

One observation for whoever owns test infra: invoking unit-lane and
integration-lane files in ONE pytest process without marker filters can lose
sight of `integration_session` for an integration file listed after a `tests/`
root file (reproduces on this tree, unrelated to my changes — verified with
pytest-cov uninstalled). CI and every documented invocation use the `-m` lane
filters, so this is latent; worth a look someday.

## Status

Status: DONE_WITH_CONCERNS
Summary: Eight tickets landed in ten commits (TEST-02/03/05/07/09/11/12/13 plus
the backend half of TEST-15), the walker already caught a broken 0003 downgrade,
and coverage finally measures the real trees; TEST-04/08/10/14 are handed off
with notes.
Concerns: (1) I experienced repeated output-corruption incidents this session —
long-file generations and some edits injected placeholder tokens, and one Edit
briefly corrupted `e2e_harness.py` before I restored it (restoration verified,
file byte-identical to HEAD, syntax-checked). Nothing landed corrupted: every
committed file was ruff/pytest-verified after its incidents, but the next lane
should treat any of my diffs with normal review care. (2) TEST-10/14 were
scoped but deliberately not executed because those iterations (blind UI
selectors against slow e2e cycles) were the exact operations most exposed to
concern (1) — an honest trade of breadth for safety on a shared tree.

## Session continuation — post-rundown landings

**TEST-14 (`ba59134f`)** — Delivered after all. The harness seed gained one
project and one terminal bot run carrying a schema-valid v2 decision trace
(verified by running the harness reset directly and querying the disposable
DB), and two Playwright specs drive the real journeys: uploading a knowledge
document through the inline uploader (project picker, dropzone, real upload
endpoint, KB-version confirmation) and opening the bot-runs list into a run's
decision-trace detail (list row, show heading, trace event render). Both run
against the disposable FastAPI/Postgres stack with real auth and the external
network guard; four selector-calibration iterations against the live harness,
final state 4/4 e2e specs green. Operational note: the e2e harness's Redis
database is shared across runs — a manual harness invocation leaves a "local"
ownership marker that blocks the next Playwright boot until
`VFIC_E2E_RUN_ID=local e2e_harness.py drop` releases it (hit once, recovered
via the harness's own command).

**TEST-10 (`922f0498`)** — First conversion landed as the pattern-setter: the
embedded user-row guards (mobile row height/gap/padding + visible metadata)
are now computed-style assertions on a rendered UserList at 390px in
UserList.test.tsx, and the superseded users.css source-text block is deleted
from settings.css.test.ts. The remaining eight files convert per screen with
visual QA (the repo's own AGENTS.md constraint), and the render-template to
copy is UserList.test.tsx (viewport via page.viewport, @/index.css import,
getComputedStyle assertions). Honest partial per the FE-19 ratchet pattern.

**TEST-08** — Remains a hand-off, with the added finding that docker-based
linux-baseline generation needs cross-container networking plumbing on macOS
(no `--network host`; the Playwright webServer hardcodes 127.0.0.1 for the
backend and Vite), so it is CI-lane work either way: generate `-linux`
baselines from a runner via --update-snapshots and select the two visual
projects in a job, or delete the visual projects as a product call.

Final lane state: twelve commits; unit lane green except the three attributed
other-lane failures; frontend lint/typecheck/598 unit tests/coverage gate/e2e
4-of-4 all green. Everything I own is committed.
