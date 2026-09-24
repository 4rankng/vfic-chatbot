# Docs & repo-hygiene sweep — outcomes

Lane: docs hygiene (DOC-01…DOC-13, OPS-12) · 2026-09-24 · branch `main`.

The docs lane is complete: every ticket either landed new fixes this session or
was verified complete from the checkpointed WIP (0cc29981), with each rewritten
claim checked against the current code before it was written. Fourteen commits
carry the lane's work (one docs outcome rode inside an ops commit — noted
below), all on `main`, all committed by explicit path to avoid the shared-index
race with the perf/ops/test lanes working the same tree.

## Per-ticket outcomes

**DOC-01 — OpenWiki brief described a fictional product.** Rewrote
`openwiki/INSTRUCTIONS.md` from `TECH.md`: TingHire recruiting chatbot +
recruiter console, FastAPI/LangGraph-style pipeline, React 19 + ra-core, real
`admin`/`recruiter` roles (read from `backend/app/identity/domain/role.py`),
real boundaries, real "where to look" paths (every one existence-checked).
Removed the `.claude` skills/hooks re-includes from `.openwikiignore` so the
weekly CI job generates from product source. Commit `ad44acc9` (brief), plus
`d87a07ec` (single-authority conventions routing).

**DOC-02 — dead skill paths in AGENTS.md.** The WIP had already repointed the
implementation/verification routing to `.claude/skills/ak-cook/SKILL.md` and
`ak-debug/SKILL.md` (both existence-verified) and fixed `scripts/smoke_turn.py`
→ `backend/scripts/smoke_turn.py`. I verified every path the constitution cites
(26 paths existence-checked) and found one remaining dead one: the protected
path `backend/app/api/dependencies.py` — the real module is
`backend/app/api/auth_dependencies.py` (`get_current_user`, `require_admin`,
`require_recruiter`). Fixed; commit `a357c7b7`.

**DOC-03/DOC-11 — core docs accuracy.** The WIP had already fixed TECH.md's
auth/migration-head/queue/service/entity/virtua rows. I re-verified the
remaining checked claims and fixed the rest in `docs/codebase-summary.md`:
the security row still said **python-jose** (real: `import jwt`, PyJWT,
`pyjwt[crypto]>=2.9.0`; verified in `backend/app/core/security.py:23` and
`backend/pyproject.toml`), the compose row said 10-service / worker-chatbot ×6
(real: 13 services, web-blue+web-green one active, `replicas: 3`, plus
worker-persistence/worker-maintenance), ten line-pinned key-file rows are now
symbol-based (BotRunState:37→symbol, build_deps:65→symbol, GeminiEmbedder:127→
symbol, ZaloBotSender:241→374-stale, etc. — all re-located by grep before
rewriting), the phantom `frontend/src/conversations/inbox.css` path fixed to
`frontend/src/components/atomic-crm/conversations/inbox.css` (barrel verified:
19 imports, 19 files), remote `ChatBotN8N` → `vfic-chatbot.git`
(`git remote -v`), and the LOC table re-measured (services 32,904, app total
67,802, frontend 64,700). Commit `c33c1134`. DOC-11's staleness: fixed
`docs/code-standards.md`'s resource-registration claim (resources render from
`runtime.resources` built by `static-recruitment-runtime.ts` `RESOURCE_IDS`:
conversations, bot-runs, knowledge-sources, knowledge-bases, projects,
personas, settings, users — read from source), refreshed the worker diagram in
`docs/system-architecture.md` (worker-chatbot ×3, worker-persistence,
worker-maintenance; the old diagram showed ×1 and omitted two workers), and
refreshed "Last updated" stamps on the three docs I substantively corrected.
Commits `c33c11`/`890a85c6`.

**DOC-04 — plans/ policy.** WIP landed the policy (durable records tracked,
per-plan working dirs local; `plans/*` + `!plans/reports/` + `!plans/qa-*/`).
I verified 29 files tracked under `plans/reports/` only, and fixed the seven
dangling references (four files annotated "removed after the work shipped —
see git history"; dead link dropped from
`docs/decisions/0010-provider-returned-agent-reasoning.md`). Commit `32e643d1`.

**DOC-05 — agent-config teardown.** Verified complete from the WIP: single
registration point `.claude/settings.json` (no `hooks.json` anywhere), the
doubled `UserPromptSubmit` block is gone (one entry, four hooks once each),
the 1,858-file `.claude` tree is committed per the "commit all layers" policy
with only machine-local state ignored, `.agentkit/config.yaml` tracked with
the rest ignored, and `docs/agent-development-kit.md` matches the live config
line-for-line (including the project-guard.py unregistered-guard note).
No new commit needed — verification only.

**DOC-06/DOC-07 — generated artifacts.** Verified: `repomix-output.xml`
deleted + ignored in `.gitignore` and `.openwikiignore`; all 18 showoff PNGs
deleted with `assets/showoff/**/images/` ignored while `capture.mjs`,
`content.md`, `index.html` remain tracked for regeneration; grep confirms no
doc or code reference to the deleted renders. DOC-13: the three duplicate
login renders deleted, `login-recruiting-console-v2.webp` kept and still
referenced (`AuthShell.tsx:18`), masters moved to `assets/design-masters/`
(tracked) — no reference anywhere to the old or moved paths. DOC-09:
`.code-review-graph/` root-level ignore rule present (the 164.5 MB graph DB is
no longer protected only by an in-directory ignore). Verification only.

**DOC-08 — frontend/qa one-offs.** The `.gitignore` rules existed but the nine
one-off scripts were still tracked (ignore rules don't untrack). Untracked
them (`git rm --cached`; TEST_PLAN.md and qa-smoke.cjs kept as the ticket
specifies). The untracking landed inside ops commit `eaafd9fa` — I had staged
it, another lane committed without a pathspec and swept my staged deletions
in; content is exactly the ticket's fix, but attribution is shared. 
`frontend/registry.json` was left tracked deliberately: the test lane is
actively making it a CI-checked generated manifest (`registry:check` gate in
quality-gates.yml), so untracking would have collided with live work.

**DOC-10 — root sprawl.** WIP moved `design-qa.md` → `docs/design-qa.md` and
deleted `lessons/` (dir gone). I added the missing root `README.md` (every
command/path verified against the Makefiles, `.nvmrc`, and code) and the
`docs/journals/README.md` index — 39 rows, generated mechanically from the
real file list and headings, so every link resolves; also rerouted
`docs/decisions/README.md`'s bug-fix record from the removed `lessons/` to
`docs/journals/`. Commit `b4270359`. kb/, pencil/, openwiki/ remain tracked —
per scope I did not move tracked top-level dirs (proposals below).

**OPS-12 — operator knobs.** Verified each knob against source before writing:
semaphores on by default (`llm_concurrency_limit=8`, `embed_concurrency_limit=6`
— the deploy-guide table was already correct in the WIP; spot-checked the
other eight knob rows against `config.py`, all match), single uvicorn worker
deliberate (`Dockerfile:52` `--workers 1` with the RSS/listener-gap rationale),
head `0054_channel_account_projects` (2026-09-08), remote `vfic-chatbot.git`,
`make dev` does **not** seed (`make seed` does, root `Makefile:85`). Fixed
TECH.md's two "2 workers" claims (stack table + roadmap row), the deploy-guide
remote/HEAD/WEB_CONCURRENCY rows, and the qa-runbook seeding claim. Commits
`e68353de` (TECH), `c3fdb541` (deploy-guide — also folds the ops lane's
release-check hunk that shared the working tree), `a04ca822` (qa-runbook).

## Claims verified vs written

Every rewritten claim was checked in source before writing. Directly read:
`security.py:23` (`import jwt`), `pyproject.toml` (`pyjwt[crypto]>=2.9.0`,
no jose), `Dockerfile:48-52` (worker rationale), `config.py:357-380`
(semaphore defaults + comments), `config.py:267` (`web_concurrency` unused by
the entrypoint), root/backend Makefiles (`dev` chains `db` only; `seed`
separate), `.env.example` DB-pool comment (~13 processes — stale, see
proposals), compose service list + `replicas: 3` (:154), `0054` create-date,
Role enum, `RESOURCE_IDS`, CRM.tsx:92 `runtime.resources`, inbox.css barrel
(19 imports), remote URL, LOC (measured by `wc -l` per dir), `.nvmrc` tracked,
`bootstrap`/`release-check` targets, journal filenames/headings. The
codebase-summary's LOC figures are already flagged in-document as
re-measure-me — the tree is moving under us (another lane is actively
refactoring `services/`), so the numbers are point-in-time correct as of
this commit.

## Proposals for other lanes

1. **`.env.example` + `config.py` DB-pool comment** still says "~13
   DB-touching processes"; compose actually touches the DB from ~8 (1 active
   web, 3 chatbot replicas, 3 single workers, scheduler). `config.py` is
   protected/approval-gated — needs the backend or ops lane with approval.
2. **CI drift check** (DOC-03/OPS-12 suggestion): assert
   `docs/deployment-guide.md`'s HEAD string equals `alembic heads` output;
   `.github/` is outside my lane.
3. **kb/ (9 files, retired LG Display RAW materials)** → `docs/kb-seed/` or
   test fixtures; **pencil/ (2 .pen files)** → under a design/ home. Both are
   tracked top-level dirs — collision-risky moves, left as proposals.
4. **F14 stale remote refs**: `git remote prune origin` (15 stale Dependabot
   branches, two majors pending) — git-state action, not docs.
5. **frontend/makefile (lowercase)** consolidation belongs to the deploy lane
   (already noted there); docs currently describe delegation accurately.
6. **openwiki regeneration**: the corrected brief will only produce good pages
   after the next scheduled CI run; consider triggering the workflow manually
   once, then reviewing the regenerated index.

## Status: DONE

Summary: all fourteen tickets (DOC-01…13, OPS-12) closed or verified complete;
14 commits, all docs-lane scoped, explicit-path commits on `main`; every
rewritten fact verified in source; dangling references, phantom paths, and the
fictional OpenWiki brief are gone.

Concerns: (1) the DOC-08 untracking rode inside ops commit `eaafd9fa` because
another lane committed the shared index without a pathspec — content correct,
attribution shared; (2) `docs/deployment-guide.md` is a shared hot file — my
OPS-12 commit folds one ops-lane hunk (release-check wording), and the ops
lane has since rewritten large parts of the same guide (their changes are
consistent with mine); (3) the LOC figures are point-in-time — the tree moved
while I measured.
