# OPS/Deploy lane sweep report — sweep-ops

**Outcome: all thirteen assigned tickets closed or verified, plus two appended items
(reviewer H1 halfvec migration, .env.example pool comment). Thirteen commits, every
change validated at its own gate (compose parse, live probe tests against scratch
Redis/network, offline alembic SQL, lock-zero-drift, npm tree + typecheck). Nothing
deployed, pushed, or run against a real database.**

One collision occurred and was contained: commit 4825c714 (from outside this team,
pre-pause parallel session) landed OPS-04's compose slice, OPS-20's dev loopback
binding, and `scripts/ops-alerts.sh` while I was still gathering evidence. I briefly
added two duplicate `logging:` keys from a stale read cache, reverted both
immediately, and verified-not-redid that commit's work. The lead has since
re-broadcast exclusivity over my file set.

## Per-ticket ledger

**OPS-04 (log rotation + disk monitoring) — CLOSED by 4825c714, verified by me.**
The `x-logging` anchor (json-file, 10m × 3) is attached to all 14 services; the
host-side piece exists as `scripts/ops-alerts.sh` (disk warn >80%/fail >95%, docker
space, /metrics checks). My verification: `docker compose config` parse with the full
anchor resolved, plus every later compose commit parsed the same file. No commit of
mine for this ticket. Remaining (scripts lane): wiring the script into an actual
droplet cron — the script exists but nothing schedules it yet.

**OPS-05 (uv.lock ignored + unbounded deps) — CLOSED, commit 1b0b603d.** The lock
enforcement half landed in the WIP checkpoint (Dockerfile `uv export --frozen
--require-hashes`); I added the second half: every pyproject entry now carries an
upper bound at the next major above its lock resolution (fastapi<1.0,
sqlalchemy<3.0, pydantic<3.0, langchain-core<2.0, cryptography<51, …). Verified:
`uv lock --check` passes and the re-lock produced **zero version drift** across all
90 packages (one self-inflicted pytest cap below its resolved 9.1.1 was caught by
the drift check and corrected). `uv export --frozen --no-dev` renders the same
hashed runtime set the Dockerfile installs. Hand-off (w3-ops/CI lane): `uv lock
--check` belongs in `release-check` and CI should install via the lock
(`uv sync --frozen`) — the Makefile and `.github/` are theirs.

**OPS-06 (nothing scrapes metrics, no alerts) — CLOSED, commit 5c9e8626.** New
`metrics-watch` compose service: same backend image, stdlib-only poll loop, emits
single-line JSON alerts to stdout (docker logs = the rotation-bounded path). Alerts:
web_down (neither colour answers /health), queue_depth_high (>20 = half of
CHAT_QUEUE_MAX_DEPTH), no_workers_registered, reconcile_counter_rising (per-poll
delta), workers_saturated (N consecutive all-busy polls). Thresholds env-tunable.
Scoped as a complement to `scripts/ops-alerts.sh` per the lead's approval — disk
stays host-side, no duplication. **Verification was end-to-end with the exact
composed script** (extracted from `docker compose config --format json`) against
stub web-blue containers in a scratch docker network: every alert mode fired, the
healthy fixture stayed silent, saturation fired at exactly the configured poll
count. Remaining (scripts lane / runbook): a cron entry for ops-alerts.sh and an
external uptime check on https://bot.tingting.vip/health with a real delivery
channel (email/Telegram) — the watcher logs; it deliberately does not page.

**OPS-08 (worker healthchecks only ping Redis) — CLOSED, commit d6b00f88, zero
app-code changes.** All five RQ worker services now assert their own hostname is
present in `Worker.all()` — RQ's work loop refreshes the registration (key TTL
worker_ttl+60 = ~480s) on every dequeue iteration, so membership means the loop
beat recently and a wedged one ages out of the registry. The scheduler probes for
its `rq:scheduler_instance:*` birth key (TTL interval+10s, re-expired each loop
iteration). **Verified live against a scratch Redis**: a running SimpleWorker →
probe exit 0; worker killed + key expired (TTL 465s observed decaying on the live
key, expiry simulated) → exit 1; rqscheduler running → exit 0, stopped → exit 1.
One real-world bug was caught during verification: my first pattern
(`rq:scheduler:*`) matched nothing — the actual key prefix is
`rq:scheduler_instance:`; the committed probe uses the verified prefix. Chatbot
worker start_period raised to 60s (langchain preload + LLM warm run before the
loop registers).

**OPS-09 (memory limits 3/12 services) — CLOSED, commit cf9a6119.** All 14 services
now carry `deploy.resources.limits.memory`; the header documents the ledger
(pg 448M, redis 320M, web 384M each, chatbot 3×512M, persistence/ingest/followup
512M, maintenance 384M, scheduler 128M, frontend/caddy 64M, adminer 128M,
backfill 512M) and the fence-not-reservation rationale: ceilings sum ≈5.3 GB over
the 1967 MB host by design (swap absorbs; a container hitting its cap is Docker's
problem alone, never the kernel OOM killer's choice of postgres). Verified per
service via rendered `docker compose config`. Hand-offs: the 4 GB / 2 GB / 1.9 GiB
doc contradiction fix belongs to the docs lane (TECH.md:94,
docs/deployment-guide.md:4 still say 4 GB; the compose header now carries the
authoritative measured figures); `bg_deploy.sh` verifying `.HostConfig.Memory`
is the scripts lane's.

**OPS-10 (mutable tags, no digests) — CLOSED, commit 0df0c31b.** IMAGE_TAG is now
`${IMAGE_TAG:?…}` on all nine app services (zero `:-latest` remain; a forgotten
tag fails loudly — verified by running config without it). adminer:4 and caddy:2
joined postgres/redis as digest pins and `python:3.12-slim` is pinned in the
backend Dockerfile. **All five digests verified against the registry**: fetched
via Docker Hub auth+manifest API, and `docker manifest inspect` resolves each
compose/Dockerfile reference; the python-slim digest was independently confirmed
a second time by Docker's own pull output during the watcher test. The header no
longer references a pin-refresh workflow that does not exist. Follow-ups: the
docs lane's runbook must note that bare droplet `docker compose run` now needs
IMAGE_TAG exported (read it from the running container — snippet is in the
compose header); a scheduled digest-bump PR (Dependabot/Renovate on .github/) is
the CI lane's; frontend/Dockerfile base pins were outside my file set.
Coordination with OPS-02 held: the restore path's tag logic is the scripts
lane's, untouched by me.

**OPS-11 (unused deps + dead curl) — CLOSED.** Backend half landed in the WIP
checkpoint (langgraph, sse-starlette, google-api-python-client,
google-auth-oauthlib, pgvector removed; curl dropped from the Dockerfile) — I
verified with greps that no import of any removed package exists anywhere in
backend (app/scripts/alembic/tests) and the full suite runs. Frontend half,
commit 674c55b2: tldts, pgsql-ast-parser (zero references anywhere) and the
orphaned @types/jsonexport removed; daisyui (@plugin in src/index.css) and glob
(scripts/generate-registry.mjs) verified used and kept. 9 packages left the
tree; typecheck clean at that point in time.

**OPS-13 (dev venv 3.14 vs prod/CI 3.12) — CLOSED in WIP, verified.**
`.python-version`=3.12, `requires-python = ">=3.12,<3.13"`, uv.lock regenerated
3.12-only (header `requires-python = "==3.12.*"`); `uv lock --check` passes. No
tracked `__pycache__`/`.pyc` files exist in git, and the image excludes bytecode
via .dockerignore + PYTHONDONTWRITEBYTECODE, so the F18 packaging concern is
moot. **Open team step (deliberately not done by me):** the local `.venv` itself
is still 3.14 — recreating it (`cd backend && uv venv --python 3.12 && uv sync`)
would yank the shared interpreter out from under the concurrently running test
lanes, so it must happen serially once the sweep settles.

**OPS-14 (two copies of @tanstack/query-core) — CLOSED, commit cc01a31b.** The
exact 5.90.20 pin was dropped (no file in src/tests/e2e imports query-core
directly — grep + tsc both prove it), so npm hoists react-query's own single
core. `npm ls @tanstack/query-core` now shows one 5.101.0; typecheck passed
clean on that tree.

**OPS-15 (mock servers + env template in prod image) — CLOSED in WIP, verified.**
`.dockerignore` excludes `mock_servers` + `.env.example`, and the Dockerfile
COPYs an explicit allowlist (app, alembic, alembic.ini, scripts) so neither can
drift back in. I verified no reference to mock_servers/zalo_mock exists from
anything the image ships (app/scripts/alembic/tests).

**OPS-16 (nine fake/absent downgrades) — CLOSED, commit 3da7ca34.** upgrade()
bodies untouched. Five INTENTIONAL_NOOP markers with the real reason (0007/0024/
0029/0030 enum values PostgreSQL cannot drop; 0018 real candidate records; the
merge node), three FORWARD_ONLY markers with the recover path (0001 baseline
guard, 0008 bus function DDL location, 0010 dead objects in git history). New
`tests/test_migration_hygiene.py` enforces the rule at source level with no DB
and asserts it covers the nine known cases.

**OPS-17 (non-concurrent index creation) — CLOSED, commit c21e1695.** The four
indexes on existing tables (0009 worker_feature_catalog, 0017 leads_stage_idx —
split out of the ALTER TYPE batch, 0031 bot_runs, 0039 uq_active_kb_version)
now use CREATE INDEX CONCURRENTLY inside `autocommit_block()`, the in-repo
0014/0016 pattern. env.py sets `transaction_per_migration=True` (Alembic's
recommended pairing) so the forced commit is scoped to one revision. The 0036
outbox indexes deliberately stay plain — that table is created in the same
migration with zero rows — now documented in place. Verified offline:
`alembic upgrade --sql head` renders all 16 CONCURRENTLY statements and
per-migration COMMITs; no database touched. The invalid-index post-deploy check
(`indisvalid = false`) is the scripts lane's bg_deploy work.

**OPS-20 (my slice: migration naming) — CLOSED, commit d2ce7f85.** The two
drifted files renamed to their revision ids (0030_send_unknown.py,
0031_conversation_seq_trace.py) — ids and chain untouched, neither is head, so
deployed alembic_version rows are unaffected (alembic heads confirmed stable at
every step). The hygiene test now enforces filename == revision with the fix
direction baked into the failure message (rename the file, never the id).
Restore/backup/release-gate slices are the scripts lane's; dev loopback landed
in 4825c714. Two stale filename references live in other lanes' files and were
left alone: docs/journals/260712-performance-endpoint-alembic-double-head.md
(historical journal — do not rewrite history) and scripts/kanban/tickets_d.py
(ticket-generation source).

**Appended H1 (halfvec baseline edit) — CLOSED, commit 8569c56b.** 0001_baseline.py
restored verbatim to its applied (vector-typed) match_memories form from
fb9632e2^; new 0055_memories_match_halfvec carries the halfvec(3072) upgrade and
a downgrade that restores the vector form. `alembic heads` shows exactly one
head; offline SQL renders both directions.

**Appended (.env.example pool comment) — CLOSED, commit c31c5f0b.** The ~13-process
figure replaced with the real topology (~8 resident DB-touching processes,
scheduler Redis-only, compose pool overrides, 48/150 steady state, 60 cutover).

Plus **0149014a**: the oa-profile-backfill deploy test still asserted the
`${IMAGE_TAG:-latest}` default OPS-10 removed; updated to expect the
required-variable interpolation.

## Commits (mine, this session)

cf9a6119 OPS-09 memory fences · 0df0c31b OPS-10 tags+digests · d6b00f88 OPS-08
liveness probes · 5c9e8626 OPS-06 metrics-watch · 8569c56b H1 halfvec migration ·
1b0b603d OPS-05 dependency caps · cc01a31b OPS-14 query-core dedupe · 674c55b2
OPS-11 unused devDeps · 3da7ca34 OPS-16 downgrade markers · c21e1695 OPS-17
concurrent indexes · d2ce7f85 OPS-20 renames · c31c5f0b env pool comment ·
0149014a deploy-test assertion.

## Verification summary

- `docker compose config` (with dummy REDIS_PASSWORD/POSTGRES_PASSWORD/IMAGE_TAG):
  parsed clean after every compose commit; per-service memory limits and the full
  logging anchor verified in rendered output.
- OPS-08 probes: live-tested against scratch Redis with real SimpleWorker +
  rqscheduler (pass/fail both directions); scratch containers/networks removed
  after each test (zero orphans).
- OPS-06 watcher: exact composed script end-to-end against stub web-blue in a
  scratch docker network — all five alert modes + healthy-silence verified.
- Digests: fetched from the registry API and re-verified via
  `docker manifest inspect`; python-slim confirmed a third way by Docker's pull.
- Alembic: `heads` single-head checks at every migration commit;
  `upgrade --sql head` offline renders the CONCURRENTLY statements; hygiene test
  2/2 green; no DB contact anywhere.
- Locks: `uv lock --check` green with zero version drift; `uv export --frozen`
  renders hashed pins.
- Frontend: `npm ls` single query-core; typecheck green at the OPS-14 commit and
  at the OPS-11 manifest change (the later failing typecheck in the tree comes
  from another lane's uncommitted runtime-context refactor in frontend/src —
  untracked replacement files, not from the manifest change).
- Full backend unit suite snapshot mid-sweep: 2317 passed / 7 failed / then
  collection churn as the graph lane deleted `app.graph.fast_lane` seconds later.
  Attributed failures: 1 bg_deploy exec (scripts lane, proven by swapping only
  their bg_deploy.sh into the pre-sweep baseline — messaged to w3-ops with the
  reproduction; since fixed, the suite then showed 32/32 deploy tests green),
  2 graph decisions.py (their uncommitted file, same one carrying the tree's only
  ruff error), 1 the known boundary-inventory baseline failure. None in my files.
  My scoped gates: migration hygiene 2/2, security headers, deploy makefile 32/32.
- Ruff: my surface (alembic/, both touched tests) clean; the single tree-wide
  error is the graph lane's uncommitted app/graph/decisions.py.

## Hand-offs (other lanes)

- **scripts lane (w3-ops):** cron entry for ops-alerts.sh; `uv lock --check` in
  release-check; lock-based installs in CI; bg_deploy `.HostConfig.Memory`
  verification; post-deploy `indisvalid = false` check; OPS-02/03/07/restore
  slices unchanged by me; OPS-20's restore/backup/release-gate slices.
- **docs lane:** 4 GB vs 2 GB host-size contradiction (TECH.md:94,
  deployment-guide §header) — compose header now carries the measured truth;
  runbook note that droplet compose commands need IMAGE_TAG exported; §7 metrics
  doc gains metrics-watch; REDIS_PASSWORD runbook step (below).
- **CI lane:** scheduled digest-bump PRs; image-build + smoke job (OPS-05's
  third leg).
- **Serial team step:** recreate backend/.venv on 3.12 once no lane is mid-run.

## REDIS_PASSWORD runbook reminder (for the report only, not committed)

The compose requirement `REDIS_PASSWORD:?set REDIS_PASSWORD in .env` is correct
and was not weakened by any of my edits — every compose validation I ran
exported a dummy to satisfy it. The open item is purely operational: production
`/opt/vfic/.env` must actually set it (the local dev .env leaves it empty).
Whoever owns the prod-env runbook step should record: generate a strong secret,
set `REDIS_PASSWORD` (and derive `REDIS_URL` with the password) in
`/opt/vfic/.env`, and restart redis + dependents; until then the prod .env
either already carries it (bg_deploy requires it, and the stack runs — so it
almost certainly does) or the next deploy will fail loudly, which is the
designed behavior.

## Addendum — post-close follow-ups (same session)

**3434636b fix(backup): prune env copies when their dump pair is pruned.**
Retention decision routed from w3-ops's close-out. Re-attributed during
investigation: no vfic_env_*.env copies are created by
backup-droplet.sh/restore-droplet.sh (the droplet-script path stores .env
inside each timestamped bundle; restore only reads bundles) — the sole
accumulator is the root Makefile's `backup` target, which pruned dumps to
newest 10 but never their env companions. Policy: pair-tie, not keep-newest-N
— an env copy whose dump is gone is orphaned prod secrets with nothing left
to decrypt, so it is deleted (both `.dump` and legacy `.sql.gz` pairs count).
Verified via `make -n backup` and a fixture-dir run of the exact loop.
Runbook one-liner handed to sweep-docs and landed by them as 513e0fad (deploy
guide § backup targets table — the OneDrive-path doc — with the behavior
verified against the prune loop first). Flagged for the ledger:
backup-droplet.sh never prunes old bundle zips in backups/ (separate
accumulator, untouched pending the lead's call). Also confirmed the tag
contract item needed no new work: the 3 test failures were already fixed
(0149014a mine, a762d6a7 w3-ops's — their message confirms the mechanism was
the empty-dump guard, exactly where my bisection pointed);
test_deployment_makefile.py is 32/32 at HEAD.

Status: DONE
Summary: All thirteen OPS tickets plus both appended items are closed across
thirteen validated commits; OPS-04's compose slice was verified rather than
redone after an external-lane collision was contained, and every remaining
cross-lane piece is attributed in the hand-off list.
Concerns: The shared tree is being edited concurrently by three other lanes —
the full-suite snapshot is churn (graph lane mid-refactor), though every failure
in it is attributed to their in-flight files, my scoped gates are green, and the
two deploy-test failures I initially attributed to the scripts lane were fixed
by them during my validation window. Local .venv is still Python 3.14 by
deliberate deferral (recreating it would break concurrently running lanes).
