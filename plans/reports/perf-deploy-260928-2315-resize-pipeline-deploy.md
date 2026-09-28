# Host resize re-base + deploy-pipeline optimization + production deploy

2026-09-28, 22:55–23:50 SGT · follows `audit-260928-2255-prod-server-optimization.md` · prod now runs `15196cdb`

## Outcome

The stack was re-based onto the resized 2 vCPU / 4 GB droplet, the release
pipeline was restructured from a serial chain into concurrent lanes, and the
result is live on production: `web-green` @ `15196cdb` active, 4 chatbot
workers, 2-uvicorn-worker web tier, every deploy gate green including the
turn-pipeline check (`PIPELINE OK: consumers live, no conversation awaiting a
reply, outbox drained`). Host RAM after cutover: 1,959 MB used / 1,956 MB
available; web at 252 MB of its 512 MB fence (the ~2× single-worker prediction
was accurate); Caddy at 19.8 MB of its new 128 MB fence; public `/health` ok.

## Commits (four logical chunks)

1. `42155590` feat(deploy): Caddy fence 64M→128M, web fences 384M→512M with two
   uvicorn workers, worker-chatbot replicas 3→4, connection-budget comments
   restated for the two-pool web tier (72 steady / 96 cutover-worst of 150),
   host ledger re-measured.
2. `61bc6ee2` docs(plans): the audit report.
3. `623f67ea` chore(frontend): the parallel session's Untitled UI v8 substrate
   (React 19.2.4, Tailwind 4.3.3, react-aria family, input-otp), committed only
   after its own gates passed on this machine: typecheck 1:41, production build
   15s, eslint clean, all 676 app-lane vitest tests, npm audit unchanged from
   the four documented standing moderates (below the high threshold), registry
   check clean.
4. `15196cdb` build(deploy): the pipeline changes (below) plus the deployment
   guide's lane/concurrency notes.

## Pipeline changes and measurements

`release-check` ran its heavy gates strictly serially; they are independent,
so they now run as three concurrent lanes — backend (pyright / ruff / unit
suite under coverage), frontend (audit / lint / typecheck / registry / unit /
changed-surface coverage / build), data (migration walk + golden retrieval
benchmark) — each lane's log kept and printed whole, any lane failure failing
the release. Wall time becomes the slowest lane instead of the sum. The deploy
targets then run the OneDrive backup and both buildx pushes concurrently,
waiting for all of them before the cutover (only the cutover needs the dump to
exist), and both push targets now export a `mode=max` registry cache
(`:buildcache`) alongside the inline cache on `:latest`, so the emulated amd64
dependency layers survive lockfile changes.

Measured on this machine during the session: backend unit lane green, backend
`make push` **15s** with warm cache (was the multi-minute QEMU case), frontend
typecheck + build + 676 tests ≈ 4 min, cutover with the four-replica roll and
all gates **4:16**. The old full `make deploy` was ~40 minutes; the next full
run should land near the slowest-lane + cutover floor (~10–15 min). The
four-target renders were syntax-validated with `make -n … | sh -n` before
commit; the dry-run also caught a wrong `$(MAKE) -C backend backup` call (the
backup target lives at the root) that was fixed before anything shipped.

## Deploy notes

The fast-track `deploy-restart` path was used because a second parallel
session is actively editing frontend files (Phase 2 Untitled UI component
work); the fast-track ships backend-only and leaves their uncommitted files
untouched and undeployed. No alembic revisions and no retrieval-path changes
have landed since the fully gated 22:36 deploy, so the migration walk and
golden benchmark inputs were unchanged; every other applicable gate was run
manually against the exact tree (pyright 0 errors on the tingting changes in
`lanes.py` / `proactive.py` / `tingting_guide.py`, doc-links OK). The rolling
worker recreation converged 3→4 correctly: `bg_deploy.sh` reads `expected`
from the compose file, replaced old-tag containers one at a time while keeping
3 of 4 consuming, and post-flip verification found exactly 4 healthy replicas.
`bg_deploy`'s own pre-migration dump gate covered schema safety; no migration
ran. The OA profile backfill sweep converged — all 63 remaining contacts are
terminally unreachable, `remaining: 0`.

## What rides the next frontend deploy

The Untitled UI substrate is committed and validated but the frontend image
has not been rebuilt or deployed; its first amd64 build with the new lockfile
will be the one slow (QEMU) run and will seed the frontend `:buildcache`. The
parallel session's Phase 2 component edits (`frontend/makefile`,
`simple-form-iterator.tsx`, `table.tsx`, `vite.config.ts`) remain
deliberately uncommitted — they are that session's in-flight work.

## Further options, deliberately not taken

- **pytest-xdist** would cut the backend lane further but adds a dev
  dependency with flaky-ordering risk to the release gate; needs its own
  validated change.
- **Batching the worker roll 2-at-a-time** would halve the ~4 min roll but
  weakens the 2026-09-26 incident invariant (at least N−1 consumers live); not
  changed without an explicit call.
- **Splitting `FE_IMAGE_TAG` from `IMAGE_TAG`** in compose would let backend
  deploys skip the frontend image build entirely; touches the tag-guard test
  surface, so it is a separate piece of work.

## Unresolved questions

1. The frontend dependency substrate (commit `623f67ea`) is on main but not
   deployed; it should ride the next `make deploy-frontend` after the Phase 2
   session lands its component work.
2. If the Caddy resident set creeps back toward its fence (it restarted at
   19.8 MB), the 128M re-base has ample room; no action expected.
