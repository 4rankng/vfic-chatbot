# sweep-final — the final three tickets and the collected hand-offs

2026-09-24, lane sweep-final, repo `/Volumes/LexarSSD/projects/chatbot`, branch `main`.

## Outcome

Eleven commits landed. All four hand-offs are fixed and verified: the migration
0003 downgrade is repaired and the roundtrip walker runs green with an empty
ratchet, pytest-cov and pytest-timeout are declared with the CI coverage gate
actually wired, and the dead `test:unit:claude` script is gone. TEST-08 is
delivered end to end: the visual guard now runs on linux baselines generated
and verified inside the exact container image the new CI job uses, with the
backend webServer and the per-test DB reset skipped for the zero-backend visual
specs. TEST-14 was landed by sweep-tests' stand-down commit (`ba59134f` — the
lead later confirmed authorship) and I verified it by running the full
functional e2e suite: 8/8 pass across chromium and Mobile Chrome, both new
journeys included. TEST-10 is partially converted (sweep-tests' users block,
my inbox guards, two misleading pin blocks removed) with the unbatchable tail
documented below. TEST-04 joined my scope when the lead released the gate
files: the gate renamed for what it measures, the turn smoke and its
fail-closed self-test running in the release-gate CI job, release-check now
requiring a green CI run for the exact commit under release, and the disabled
latency SLO documented where it is set.

Final lanes: backend unit 2,299 passed / 24 skipped / 2 failed (the two known
frontend-boundary failures that predate this session), ruff clean, migration
walker green, functional e2e 8/8, visual guard 4/4 (darwin and linux), frontend
lint / typecheck / prettier clean, app unit lane 593 passed with the coverage
gate green.

## Hand-offs, by ticket

**Migration 0003 downgrade (`df7314d0`)** — the roundtrip walker proved
`downgrade 0003 → 0002` raised `InvalidTableDefinition: cannot drop columns
from view`. `CREATE OR REPLACE VIEW` can append columns to a view but can never
remove the `project_id` column that upgrade() added, so the project-less
restore now drops the view and recreates it. Nothing depends on the view in DDL
(match_documents is plpgsql — body references create no dependency), the
walker's re-upgrade of 0003 after the downgrade proves the restored state is
the correct input to 0004's upgrade, and the `KNOWN_BROKEN_DOWNGRADES` ratchet
is emptied. Evidence: the walker covers all 58 revisions upgrade → downgrade −1
→ upgrade and passed in 129.60s with the empty ratchet set. upgrade() is
byte-identical.

**pytest-cov declaration + CI coverage gate (`e16cee6c`)** — pytest-cov joins
the dev extra (>=5.0,<8.0); the backend-unit CI job now runs the exact command
the .coveragerc header documents (`pytest -m "not integration" --cov
--cov-config=.coveragerc --cov-report=term-missing`), proven locally on a unit
subset (24 tests measured, report rendered). The frontend coverage step keeps
its command but drops the no-longer-accurate "Changed-surface" label; the npm
script name stays because docs/testing.md references it and docs beyond the
one-line runbook note were out of my scope. The .coveragerc header no longer
claims the config is dormant. `fail_under` stays 0 (report-only) — the first
CI run's measured number should become the floor; that is a maintainer decision
recorded here.

**pytest-timeout + hang guards (`1e466bb5`)** — declared (>=2.3,<3.0) and
applied as module-level 30s per-test timeouts on the two suites the TEST-11
conversion touched (`test_parallel_tools.py`, `test_graph_runner_turn.py`),
with comments noting the converted tests observe scheduling rather than
wall-clock budgets. Verified 116 tests pass and that the `timeout` mark
escalates `PytestUnknownMarkWarning` to error without failing, proving the
plugin registers the mark.

**`test:unit:claude` removal (`773409a7`)** — the last remnant of the removed
vitest claude project is gone; JSON validated, no other code references the
script. Note for the docs lane: `frontend/README.md`, `docs/code-standards.md:273`
and `docs/testing.md:117` still mention the removed script (docs/ beyond the
runbook note was out of my scope; openwiki regenerates itself).

## TEST-08 — visual guard enforced on linux

Three commits (`53eb9799`, `48d5fe07`, `baa0df45`). The visual specs render
unauthenticated zero-backend pages only, so the design makes that explicit:
tests carry an `@visual-only` tag and the auto `resetDb` fixture skips the
harness DB reset for tagged tests; `VFIC_VISUAL_ONLY=1` skips the backend
webServer and the teardown DB drop. The four `-linux` baselines were generated
and verified inside `mcr.microsoft.com/playwright:v1.60.0-noble` (pinned from
the lockfile's 1.60.0) via docker on this machine, using an anonymous-volume
node_modules overlay so the host install was untouched; a second in-container
run without `--update-snapshots` verified them. The CI `visual-e2e` job runs
both visual projects inside that same pinned image — the byte-identical
rendering environment argument — with `npm ci` and no database services. The
functional e2e suites still pass against the untouched darwin baselines, which
proves login-shell pixels are backend-independent (both baseline families hold
under the new zero-backend condition). One runbook sentence in docs/testing.md
covers the zero-backend visual run and the linux baseline regeneration
workflow.

## TEST-14 — verified the concurrent writer's landing

`ba59134f` (not my commit) adds the two journeys the card asked for: a knowledge
document uploaded through the console until the console confirms the KB version,
and a bot-runs list → decision-trace detail render, backed by a harness seed
extension (one project, one terminal bot run carrying a schema-valid v2 trace).
I ran the full functional suite on the disposable stack: 8 passed (4 tests ×
chromium/Mobile Chrome), external-network guard still enforced by the fixtures.
No follow-up owed from my lane beyond this verification.

## TEST-10 — what converted, what remains

`922f0498` (not my commit) converted the embedded user-row pins to a rendered
computed-style test in UserList.test.tsx (84px rows, 4px gap, padding, and
metadata cells staying displayed at 390px). My `33a96c3e` converts the inbox
surface: the e2e journey now proves on rendered output that the removed count
badge, queue filters and `tt-btn` row treatment stay absent from the list, and
that channel-adapter icons and the reply-mode trigger icon keep their 44px/20px
mobile touch-target sizes. The superseded component-source pins came out of
ConversationList.test.ts and tailkit-redesign.test.ts was deleted.

The conversion immediately caught a real source-vs-reality divergence: the
deleted pins claimed a 36px desktop adapter icon, but the cascade renders
30px — the exact failure mode the card describes (source text passes while
rendered layout differs). The e2e records measured reality on desktop and pins
the mobile touch target exactly.

The tail that remains (7 files, roughly 30 assertions — settings.css.test.ts,
responsive-visual-regressions, tailkit-system.css.test.ts, projects.css.test.ts,
performance.css.test.ts, persona-layout-regressions, account-layout-regressions,
knowledge-workspace-layout) pins design-language CSS text. Per-file conversion
is genuinely unbatchable: each feature needs its own render harness (mocked
ra-core surface with a form shim for users, provider mocks for settings, a real
ra-core CoreAdminContext with a memory dataProvider if the admin inputs' useInput
must be exercised for real), and every written assertion must be verified
against a real browser render. The mechanical plan, same bar as FE-19: per
feature, (1) render the list/form component with the UserList harness pattern,
(2) convert the touch-target, viewport-overflow and hidden-metadata pins to
computed-style assertions at a 390px viewport, (3) delete the design-language
pins — the login shell is now pixel-guarded in CI and the css-scoping ratchet
bounds rule growth — and (4) land per-file. I left the remaining source-text
pins in place rather than deleting guards ahead of replacements; the card is
closed on the board but this tail is the honest remainder of TEST-10.

## TEST-04 — delivered after the lead released the files

The lead released `release_gate.py`, its tests, and the Makefile/quality-gates
lines mid-session, after I had assessed the card against the tree w3-ops
already landed: release-check runs the full lanes, the single-alembic-head
check, and the docs-drift assertion, so the card's "release-check re-runs the
same benchmark and never checks CI" claim was only partly true. Four gaps
remained and all four are closed.

**The rename (`daeed012`)** — the gate labelled its golden-dataset pass-rate
check "correctness" while it measures retrieval precision on a committed
fixture scored with canned embeddings. The gate is now `retrieval_correctness`
in every failure detail and not-evaluated report (release_gate.py, 4 label
sites; test_release_gate.py, 3 assertions; test_release_gate_cli.py, 1 expected
output string). The controlling setting keeps its historical
`release_gate_correctness_enabled` name — config.py is approval-gated and the
setting is deployment surface; a comment in release_gate.py records the
deliberate mismatch.

**The turn smoke in CI (`75c27fd5`)** — the release-gate job now boots the
disposable PostgreSQL/Redis services, migrates the database to head, runs
`scripts/smoke_turn` (one real turn through the live service layer, LLM and
Zalo transport stubbed), and proves the smoke fails closed: the `--inject-failure`
self-test must exit non-zero or the job fails. Verified locally by replicating
the exact CI sequence against a fresh empty database: migrate → smoke exit 0 →
inject-failure exit 1.

**CI-status requirement (`6e51bdf8`)** — `release-check` now requires a green
quality-gates run for the exact commit under release before any deploy target
proceeds. Verified against the live repo state: HEAD is unpushed, the
`gh run list --commit HEAD --status success` query returns nothing, and the
release blocks with the reason. A missing `gh` CLI blocks too instead of
skipping silently.

**Latency documented (`75c27fd5`)** — `RELEASE_GATE_LATENCY_SLO_ENABLED=false`
now carries the explicit decision where it is set: CI cannot supply the
30-run production telemetry window the gate requires, synthetic seed telemetry
is excluded from release evaluation by design, and latency stays observable
post-deploy. The card's "enable or document" ask is satisfied by documenting;
enabling would need the production telemetry window and is a maintainer
decision recorded here.

Also verified while assessing: the card's `--min-pass-rate 0` observation
stands but is harmless — the benchmark artifact feeds release_gate_check.py,
which fail-closes on the 95% threshold; the benchmark's own exit code is not a
gate. docs/deployment-guide.md:77 still says "the offline golden correctness"
— one optional word-level docs touch for whoever owns docs, not blocking.

## Notes and anomalies

- **Concurrent writer (resolved).** Two commits (`ba59134f`, `922f0498`) landed
  in my lane's exclusive file set from another session before the lead
  confirmed them as sweep-tests' stand-down work and closed TEST-14 and
  TEST-10-partial on the board. The work is real and I verified both commits
  by running them. The TEST-10 card closed with roughly 30 source-text
  assertions remaining — the lead accepted this as the FE-19-style honest tail
  (per-screen visual-QA work the repo's AGENTS.md forbids batching), and the
  conversion plan is documented in the TEST-10 section above.
- **Output corruption.** This session repeated the previous lane's incidents:
  several Edit/Write payloads were injected with placeholder tokens (two landed
  in files, one Write truncated playwright.config.ts mid-payload). Every
  instance was caught by post-edit git-diff verification, repaired, or restored
  from HEAD single-file; every committed diff was inspected before commit. No
  corruption is in any landed commit.
- **Coverage floor.** The backend coverage gate is report-only by design; the
  first CI run's number should be set as `fail_under` (raise-only) by whoever
  merges.
- **Residual risk on the visual baselines.** The docker baselines were
  generated on linux/arm64 and the CI runner is linux/amd64 — the same pinned
  image and Chromium build, identical font binaries, and a 10% diff tolerance,
  but the proof is the first CI run of `visual-e2e`. If it disagrees, regenerate
  on an amd64 container with the same documented command.
- The walker's alembic `path_separator` deprecation warning is pre-existing and
  out of scope.

## Verification

Backend unit lane after all commits: 2,299 passed, 24 skipped, 2 failed (the
two known frontend-boundary failures from before this session). Ruff clean.
Migration walker: 1 passed in 129.60s with the ratchet empty. Functional e2e:
8 passed across both projects (includes the two new TEST-14 journeys and my
new rendered guards). Visual guard: 4 passed under `VFIC_VISUAL_ONLY=1` on
darwin against the darwin baselines, and the linux baselines verified in-image
twice. Frontend: lint, typecheck, prettier clean; app unit lane 593 passed with
the coverage thresholds met.

## Status

Status: DONE_WITH_CONCERNS
Summary: All four hand-offs fixed and verified (0003 downgrade walker-green
with an empty ratchet, pytest-cov + CI coverage gate, pytest-timeout hang
guards, dead script removed), TEST-08 delivered end to end (zero-backend visual
harness, in-container linux baselines, container-pinned CI job), TEST-14
verified green 8/8 after sweep-tests' stand-down commit, TEST-10 advanced with
rendered guards and a real source-vs-reality catch, and TEST-04 delivered after
the lead released the gate files (retrieval_correctness rename, turn smoke +
fail-closed self-test in the release-gate job, release-check CI-status
requirement, latency decision documented) — eleven commits total.
Concerns: (1) The TEST-10 card closed on the board with roughly 30 source-text
assertions remaining; the lead accepted this as the honest tail and the
conversion plan is documented above. (2) The visual-e2e CI job is unproven
until its first run (arm64-generated baselines on an amd64 runner, same pinned
image and 10% tolerance); regeneration is one documented docker command if
needed. (3) Repeated output-corruption incidents again this session; all
repaired and nothing corrupted was committed, but diffs deserve normal review
care. (4) The backend coverage gate is report-only until whoever merges sets
the first CI number as the raise-only floor.
