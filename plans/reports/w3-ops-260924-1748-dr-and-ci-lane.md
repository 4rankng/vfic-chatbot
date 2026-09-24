# Wave 3 — DR backup/restore trio + CI lane (OPS-01, OPS-02, OPS-03, TEST-01)

Outcome first: the disaster-recovery pair (`make backup-full` / `make
restore-prod`) is now internally consistent — backup can always produce a
complete bundle, restore can always consume one, restore pins the exact image
tag the dump was taken at and refuses to boot a schema the pinned image does
not expect, and the credential-sealing key travels with every backup path and
is proven to decrypt what it sealed before any restore declares success. The
deploy gate and CI now run all 29 backend integration files (116 tests,
39 s locally) instead of the single harness smoke. Four commits, all
validated locally; nothing was run against any real droplet.

Commits, in order: `98700969` (OPS-01), `750c0572` (OPS-02), `bc069298`
(OPS-03), `5f8e2378` (TEST-01). Important context: a `wip` checkpoint commit
(`0cc29981`) landed mid-flight and committed a half-finished predecessor's
script edits to HEAD — the backup/restore guards, manifests and tag-resolution
scaffolding in that checkpoint are the base my commits complete and wire up.

## OPS-01 — backup died on a non-existent Caddyfile; restore demanded it back

The Caddyfile snapshot guards, the rendered `/opt/vfic/Caddyfile` fetch and
restore's rendered-or-template acceptance were already in the checkpointed
base; what was still broken was the rest. The kb_uploads capture and restore
seed addressed a `web` compose service that does not exist (the compose file
has only `web-blue`/`web-green`), so the volume step died on every run — both
now go through `worker-ingest`, which mounts `vfic_kb_uploads` independent of
the active colour (`scripts/backup-droplet.sh:99-104`,
`scripts/restore-droplet.sh:196-198`). Restore now actually renders a
template-only bundle (the base declared `RENDERED_TMP` but never used it):
`sed "s/__WEB_UPSTREAM__/web-<colour>/g"` — the identical substitution
`flip_caddy.sh` performs — and also ships the template to
`/opt/vfic/Caddyfile.template` so later cutovers can re-render
(`scripts/restore-droplet.sh:151-167`). Verified: dry-run with a synthetic
template-only bundle renders upstream `web-green` and completes all 9 remote
steps; `bash -n` on both scripts.

## OPS-02 — restore pinned `latest`; no schema compatibility check

Restore now resolves the image tag from the bundle (`--tag` > recorded
`manifests/image-tag.txt` > `docker-images` manifest fallback) and refuses
`latest`/empty/`<none>` with exit 2 and a remediation hint — verified for all
three refusal shapes and for fallback precedence. Every compose invocation
(pull, seeds, `up postgres redis`, pg_isready, psql load, alembic runs,
`up -d`, verification) exports `IMAGE_TAG=$TAG`. After the dump loads, new
step 6/8 runs `python -m scripts.widen_alembic_version` and
`alembic upgrade head` inside the pinned image, then asserts the restored
`alembic_version` equals the image's `alembic heads` — a no-op when they
already agree, a forward migration when the image is slightly newer (the same
additive assumption every deploy makes), and a loud failure when the dump's
revision is foreign to the image. Step 8/8 proves the serving container's
image tag equals the pinned tag and that `/health` answers, and the droplet
gets `ACTIVE_COLOR`/`PREV_COLOR`/`PREV_TAG` state files. On the backup side,
the compose tag is now resolved from the active colour's *running container*
via plain `docker ps`/`inspect` (not `ACTIVE_TAG`/`PREV_TAG` files, not
compose) — this matters because `compose run` pulls whatever tag it
interpolates, and the old `unknown` placeholder would have tried to pull
`tinghire-be:unknown`; the manifests record active colour, running tag and
alembic revision for restore to consume. The droplet-side "fail closed when
ACTIVE_COLOR's tag drifts" guard is OPS-10's compose/bg_deploy territory and
was left to that lane.

## OPS-03 — `make backup` shipped a dump that could never decrypt

The key now travels on both backup paths. `make backup` pulls `/opt/vfic/.env`
beside the dump as `vfic_env_<ts>.env` (chmod 600 local and remote) and warns
when it lacks `INTEGRATION_SETTINGS_ENCRYPTION_KEY`; `backup-full` refuses
outright to produce a bundle whose `.env` carries neither that key nor
`JWT_SECRET`. `make restore` derives the backup's effective sealing key
(dedicated key, `JWT_SECRET` fallback) and compares it to `backend/.env`
*before* touching the dev database — mismatch fails the target with the exact
remediation (copy the key, or `ALLOW_KEY_MISMATCH=1` to acknowledge) — and
after loading runs the new probe. The probe is
`backend/scripts/verify_integration_secrets.py`: it opens every sealed
`integration_settings` row with the current environment's key and exits 1 on
the first `InvalidTag`, printing row keys and counts, never secret material.
`restore-droplet.sh` pipes the same probe over stdin into the pinned image
(`docker compose run … python -`), so images that predate the script are still
covered; the in-container probe reads the restored `.env` via the service's
`env_file`. Verified against the live dev DB: a row sealed with the dev key
passes (rc 0, "all 1 sealed row(s) decrypt cleanly"), a row sealed under a
wrong key fails (rc 1, names `__probe_bad__`, no values printed), synthetic
rows removed afterwards (rc 0 on the empty set). The key-derivation logic in
the Makefile was additionally unit-run standalone under `sh` (mismatch and
JWT-fallback cases). Docs: `docs/deployment-guide.md` §8 table rewritten to
match the scripts exactly and §10 gains "The sealing key is DR-critical"
(password-manager storage, `JWT_SECRET`-rotation hazard, both paths carrying
the key, restore-time verification).

Scope disclosure: the OPS-03 commit includes, as-is and disclosed in its
message, the concurrent lane's already-in-tree Makefile hardening (custom-format
dump with compose-resolved container names, `ON_ERROR_STOP`, prune-to-10,
optional password reset prompt) — my additions are textually interleaved with
that rewrite, so index-only staging of my hunks alone was not possible; the
lead was informed before the commit.

## TEST-01 — gate ran 1 of 29 integration files

`Makefile:21` (release-check) now runs the harness smoke first as a fast-fail
canary and then the full lane: `.venv/bin/pytest -m integration
--durations=25`; `.github/workflows/quality-gates.yml` mirrors it in a renamed
smoke step plus a "Backend integration suite" step, with the job's
`timeout-minutes` raised 20 → 45 (the migration tests chain alembic
subprocesses at 120 s timeout each; the whole lane is ~39 s locally, so 45 min
is generous CI headroom). Lane math: 1 file → 29 files; 3 tests → 116 tests.
Missing services fail rather than skip: `tests/integration/conftest.py`
already treats unreachable infrastructure as a session error ("It never
skips"), so a gate without the dev stack errors loudly instead of going green
— no change needed there. Evidence: full local run
`cd backend && .venv/bin/pytest -m integration --durations=25` →
**116 passed, 2479 deselected, 39.38 s**, slowest single test 5.07 s
(canonical-channel downgrade); `make -n release-check` shows both invocations;
workflow YAML parses via `yaml.safe_load`. Note this run executed against the
shared working tree, which carries other lanes' uncommitted backend edits
(outbox/zalo/reconcile) — the 116-pass result covers that combined state.

## Evidence index

- `bash -n` on both scripts after every state (final: OK); `make -n` parses
  for backup / restore / backup-full / release-check; workflow YAML parses.
- Dry-run matrix on synthetic bundles in /tmp: template-only bundle renders
  and completes; `--tag latest` → refusal exit 2; no tag manifest → refusal
  exit 2; docker-images fallback parses (`abc123def`), image-tag.txt wins
  (`sha-deadbeef`); 9 remote calls in the full plan.
- Probe positive/negative/post-cleanup against dev Postgres (rc 0 / rc 1
  naming the bad row key / rc 0), synthetic rows deleted afterwards.
- Full integration suite: 116 passed in 39.38 s (see above).
- Ruff clean on the probe script; `git show --check` clean on all four
  commits; no TODO/FIXME/HACK introduced; no secrets or key material printed
  anywhere (probe output is counts + row key names only).
- Docs: every §8/§10/§3 claim re-checked against final script text after a
  later docs-reconciliation commit by another lane (my claims survived).

## Process notes for the lead

- Two shared-index collisions occurred (other lanes left staged entries):
  my first commit briefly swept 9 staged `frontend/qa` deletions (soft-reset
  and recommitted clean as `98700969`; their deletions restored to unstaged),
  and TEST-01's staging briefly included 28 staged ingestion deletions
  (unstaged before committing; worktree untouched). Lanes should commit or
  unstage promptly.
- Per the constraints, no end-to-end rehearsal against a throwaway droplet
  was performed (forbidden this wave). The tickets suggest recording a
  rehearsal date in the runbook once run — that remains open.

## Unresolved questions

1. `docs/DROPLET-BACKUP-RESTORE.md` (not my file) still describes the old
   bundle layout — and `backup-droplet.sh` embeds it into every bundle as
   `README-RESTORE.md`, so stale instructions ride each backup. It needs the
   same rendered-Caddyfile/manifest/tag-pinning updates.
2. The OPS-01/OPS-02 tickets ask for an end-to-end droplet rehearsal with the
   date recorded — needs an approved window; local validation is all this
   wave could do.
3. Runtime `InvalidTag` handling in
   `backend/app/services/integration_settings.py` still warns-and-falls-back
   by design; restore-time detection now catches it, but the runtime skip
   behavior itself was out of my file ownership.
4. Droplet-side tag-drift fail-closed (ACTIVE_COLOR vs running container tag)
   sits with the OPS-10 compose lane; my restore verifies its own outcome but
   ordinary reboots/flips are still that lane's gap to close.
5. `make backup` prunes dumps to the newest 10 but never prunes paired
   `vfic_env_*.env` files — OneDrive will accumulate key-bearing env files
   indefinitely (arguably correct for key retention, but the owner of the
   OPS-20 hardening should decide deliberately).

Status: DONE_WITH_CONCERNS
Summary: All four tickets implemented and locally validated across four
per-ticket commits (98700969, 750c0572, bc069298, 5f8e2378); the DR pair is
consistent and tag/schema-gated, the sealing key travels with every backup
and is verified by decrypt probe, and the gate runs all 29 integration files
(116 tests, 39 s). Concerns: no real-droplet rehearsal (forbidden), the
DROPLET-BACKUP-RESTORE.md runbook drifts, and one commit necessarily carries
a concurrent lane's Makefile hardening (disclosed in its message).

---

# Addendum — scope extension (OPS-07, OPS-18, OPS-19, TEST-06)

The lead appended four tickets to this lane. Two were already finished by
another lane; two are implemented here, bringing the lane to six commits
total: `98700969`, `750c0572`, `bc069298`, `5f8e2378`, `28626ffe` (OPS-07),
`543aabd8` (TEST-06).

## Adopted-Makefile validation (lead's condition on `bc069298`)

The unclaimed working-tree rewrite adopted as the Makefile base was validated
before committing: every target does what its name claims (verified by code
reading plus `make -n` parse for backup / restore / backup-full / dev /
bootstrap / release-check — none of them executes at `-n`), no target prints
key material or passwords — the backup's key check is `grep -q` on a path
(presence only, no values), restore compares keys inside shell variables and
echoes only paths, prompts and remediation text — and `ALLOW_KEY_MISMATCH`
defaults to unset, so the mismatch gate is fail-closed unless explicitly
overridden. The key-derivation logic was unit-run standalone under `sh` for
both the mismatch and JWT-fallback cases. Attribution is recorded in
`bc069298`'s commit message and in the first section of this report.

## OPS-07 — migrations ran with no pre-migration dump and no lock_timeout

`backend/scripts/bg_deploy.sh` now takes a compressed custom-format `pg_dump`
to `/opt/vfic/pre-migration-dumps/vfic-pre-<ts>-<tag>.dump` (newest 5 kept,
`PRE_MIGRATION_DUMP_KEEP` overridable) immediately before step 3, and aborts
the deploy — old colour still serving, no migration executed — when the dump
fails or is empty, since a dump is the only rollback for one-directional
migrations such as 0017's lead-stage collapse. `backend/alembic/env.py` bounds
the migration connection: `lock_timeout=5s` and `statement_timeout=15min`
applied via psycopg `connect_args` session options, env-overridable
(`ALEMBIC_LOCK_TIMEOUT_MS` / `ALEMBIC_STATEMENT_TIMEOUT_MS`, 0 disables), so a
DDL lock queued behind a long-running query fails the deploy loudly instead of
hanging it forever. Evidence: `bash -n` on bg_deploy.sh; ruff + py_compile on
env.py; a full `alembic upgrade head` against a scratch database through the
new connect args (ran to head, `0054_channel_account_projects`); and a direct
session probe proving the mechanism reaches the server —
`lock_timeout=5s statement_timeout=15min` read back via `SHOW` — before the
scratch DB was dropped. Boundary note: env.py sits under `alembic/`, which the
original wave brief listed as untouchable, but the ticket's approved fix names
it explicitly (and the AGENTS.md approval gate covers only
`alembic/versions/*.py`); the timeout applies from the next image build
onward, since the deploy's one-shot runner uses the freshly pulled image.
Docs: deployment-guide §3 cutover step 3 rewritten to match.

## TEST-06 — no dependency or security scanning in CI

Added `.github/dependabot.yml` (weekly, grouped, `chore(deps)`-prefixed PRs
for the backend pip manifest and the frontend npm manifest) and an advisory
`dependency-audit` job in `quality-gates.yml`: `pip-audit --strict` over the
installed backend environment and `npm audit --omit=dev` over the frontend
production tree, both `continue-on-error: true` so advisory-database findings
surface as red logs without blocking merges on unfixed upstream CVEs. The
promotion path (remove `continue-on-error`) and the accepted-risk convention
(commented `--ignore-vuln` entries with reason and date, never silence) are
documented in the job itself. Evidence: both YAML files parse via
`yaml.safe_load`; job inventory confirms `dependency-audit` alongside the five
existing jobs; the workflow diff contains only the new job.

## OPS-18 / OPS-19 — verified already complete (no new work)

Both cards were in `DEV_COMPLETED` when the scope extension arrived — the
lead's snapshot was stale. Verified rather than redone: `29446018` (bootstrap
target: guarded `backend/.env` creation, 3.12-preferred venv with fallback
warning, `pip install -e backend/[dev]`, `npm ci`; `dev` depends on it) and
`c37ef6a5` (root `README.md` present with the one-command path;
`docs/qa-runbook.md` now states `make dev` does not seed and points at
`make seed`). OPS-19: the root Makefile documents the three real port
variables, `PORT ?= $(FRONTEND_PORT)` keeps the documented alias working, and
`dev` forwards `FRONTEND_PORT=$(PORT)` — the dead plumbing is gone
(`make -n dev` confirms). No commits from this lane; the board evidence logs
match the tree.

## Makefile audit pass (`42c89829`)

The lead asked for a semantic audit of every backup/restore/release target in
the adopted base, beyond the parse-level validation recorded above. Method:
line-by-line trace of each recipe's shell semantics (quoting, `$$` expansion
through single-quoted ssh commands, exit-code propagation under
`set -euo pipefail`), `make -n` across all twelve targets, and targeted `sh`
tests of the constructs whose behavior wasn't obvious. Four claim/behavior
mismatches found and fixed, plus one stale comment:

- The uv lock gate (`command -v uv && uv lock --check || warning`) downgraded a
  failing lock check — with uv installed and a stale lockfile — to the
  "uv not found" warning and continued the release check. Now an explicit
  if/else: a failing check fails the gate; a missing uv only warns. Verified
  with stand-in commands (missing → warning rc 0; failing → rc 3, no warning).
- The restore password-skip message claimed `FORCE=1` skips the prompt; FORCE
  actually resets without asking, and the skip happens on a "no" answer. The
  message now states what FORCE does.
- `pg_restore` gained `--exit-on-error`, matching the SQL path's
  `ON_ERROR_STOP` intent — a failing custom-format restore now aborts at the
  first error instead of collecting them to the summary.
- The bootstrap comment no longer claims repeat runs are a no-op (the
  editable-install re-sync runs every time by design), and the deploy comment
  names the real registry (GHCR).

Checked and found sound: `xargs -r` in the backup prune (supported on this
machine's xargs and a no-op on empty input), the remote `$$(...)` quoting in
the backup ssh commands, the `$(or ...)` host default in restore-prod
(empirically expands correctly on the installed make), the `BACKUP_ENV`
timestamp pairing for both dump formats, the prune arithmetic, and the
`tail -n +N`/`2>/dev/null` guards. One pre-existing hang risk noted, not
fixed (out of claim scope): `make restore`'s `until pg_isready` loop is
unbounded if postgres never becomes healthy.

## Final lane commit list

`98700969` (OPS-01) · `750c0572` (OPS-02) · `bc069298` (OPS-03) ·
`5f8e2378` (TEST-01) · `28626ffe` (OPS-07) · `543aabd8` (TEST-06) ·
`42c89829` (Makefile audit) · `feb38b13` (docs-drift gate, routed from
sweep-docs) · `4b2bf20a` (droplet restore fail-fast load, routed from
sweep-docs). OPS-18/19 carried by `29446018` + `c37ef6a5`
from their original lane, verified here.

## Droplet restore load semantics (`4b2bf20a`)

Sweep-docs flagged that the droplet restore loaded the dump with
`ON_ERROR_STOP=0` while every other path fails fast. The live comparison made
the switch more than parity: psql *without* ON_ERROR_STOP exits 0 after a
script whose errors are followed by a successful statement — a scratch-DB load
with a mid-script error returned rc=0 and kept loading — so the old rc-gate
was blind to exactly the partial-load case the revision assertion cannot
catch (alembic_version loads early; later rows can error). The droplet path
now runs `ON_ERROR_STOP=1` (fail at the first bad statement, matching
`make restore`'s SQL path and `pg_restore --exit-on-error`), with the rc-gate
and log tail retained as the second net for transport failures and truncated
gzip. Evidence: scratch-DB comparison — `ON_ERROR_STOP=1` rc=3 with the load
stopped at the first statement pair, `ON_ERROR_STOP=0` rc=0 with the whole
script loaded despite the mid-script error; `bash -n` clean. A third
shared-index collision occurred during the commit (two staged test deletions
from another lane briefly rode it); soft-reset and recommitted clean — their
deletions restored to unstaged.

## Docs-drift gate (`feb38b13`)

Routed from sweep-docs: `docs/deployment-guide.md` §4's `**HEAD:** <rev>`
line kept drifting from the actual alembic head. Both release-check (right
after the existing single-head assertion) and the CI backend-unit job (after
Ruff) now resolve `alembic heads` and fail with a pointed message unless the
guide names that revision — the next migration that lands without its doc
update blocks its own release. Validated live: the current head
(`0054_channel_account_projects`) matches and passes; a fabricated revision is
rejected; `make -n release-check` parses; workflow YAML parses. The check runs
after the single-head assertion, so a branched history fails there first with
its own message.
