# Project Roadmap

**Last updated:** 2026-09-21
**Production:** `bot.tingting.vip` — stable, serving candidates over Zalo.

---

## 1. Current state

Ting Ting is **in production** at `bot.tingting.vip`. The core recruiting
chatbot loop is live:

- Zalo Bot Platform inbound + outbound, <1s webhook ack, async turn pipeline.
- MiniMax M2.7 agent + M2.5 safety, selectable OpenRouter provider, pgvector RAG.
- Explicit vacancy questions now take a deterministic active-job path before
  FAQ/RAG/LLM handling. Only `ACTIVE` jobs with positive vacancies can support
  a current-hiring claim; a true no-match and a lookup outage produce distinct
  candidate-facing replies.
- Recruiter console (React Admin, Vietnamese-only) with realtime Socket.IO
  inbox, lead kanban, knowledge base, projects.
- Proactive follow-up removed (2026-10-04) — the bot no longer initiates
  contact. Recruiter follow-up tasks and reactive opt-out matching remain.
- Reconcile worker recovers lost turns after crashes (~3-4 min).
- Auth via JWT (replaces Supabase Auth, decommissioned 2026-06-26) with
  `token_version` revocation.
- Alembic HEAD = `0066_drop_persona_storage` (4 Oct 2026).
- Manual deploy via `make deploy` over SSH (no CI deploys to prod).

Zalo Official Account integration is implemented in the working tree and
documented here; verify maturity before relying on it in prod.

### Project-owned knowledge modes

This work is implemented in the current worktree and covered by integration
tests, but it has not had a production cutover yet.

- Each Project owns exactly one knowledge mode: `DIRECT_CONTEXT` or `RAG`.
- `DIRECT_CONTEXT` stores one full page and replaces that page on save instead
  of chunking, embedding, or RAG retrieval.
- `RAG` replaces knowledge through 12 independent YAML categories: jobs,
  compensation, requirements, work schedules, benefits, accommodation, meals,
  transportation, insurance, application, contacts, and FAQ.
- Conversation scope uses `EXPLORE` when no Project is selected and `FOCUSED`
  when one Project is explicitly selected.
- Migration `0048_project_owned_knowledge_modes` is prepared to link the legacy
  LG Display KB and seed category rows; it has not been deployed to production.
- Verification is local/integration only. Production validation remains pending.

### Phase 1 baseline milestone (2026-07-15)

Phase 1 established test-only characterization fixtures, fallback/runtime
inventories, a mandatory selected PostgreSQL + pgvector integration lane, and
an isolated FastAPI/JWT/Playwright harness. It freezes current recruitment
behavior without changing production runtime code; the platform remains
recruitment-specific and is **not** yet a universal-industry platform.

### Universal-platform foundation through Phase 4 (2026-07-15)

- Phase 2 added immutable PostgreSQL installation authority and a closed,
  source-owned pack/capability registry. Phase 3 added the administrator setup
  workspace; business configuration is selected in Settings and stored in the
  database rather than business environment variables or browser fallbacks.
- Phase 4 added the dormant backend/frontend capability compiler, canonical
  `recruitment@1` parity artifact (hash
  `29aaea6c8508d4da77b8abbb63b14e566ce415fcb29f1313d6232b9da175a06a`),
  immutable workflow authoring, typed Contacts/channel identities, generic
  workflow-pinned Cases, and generation-owned frontend reset. The frontend
  renders compiled React Admin resources/routes directly and fails closed on
  unknown or colliding composition.
- Migration `0044` inserts no customer, workflow, stage, tag, Contact, Case,
  persona, template, credential, or sample row. Administrators must explicitly
  author and select an immutable workflow version/checksum.

This is an activation-preparation *foundation*, not a live universal product.
Every shipped pack remains `runtime_ready=false`; activation still returns
`INSTALLATION_RUNTIME_NOT_READY`. The live Zalo webhook, workers, provider
dispatch, Socket.IO rooms, graph, prompts, safety, grounding, tools, and legacy
recruitment routers remain unchanged.

Before any readiness flip:

1. **Phase 5 — runtime policy authority:** compose pinned policy/tool authority
   and fence active-KB mutation. (The setup persona contract that serialized the
   hard-coded recruitment keys `hot`, `warm`, and `not_interested` is gone with
   the persona tables in `0066`; the persona is now a code constant.)
2. **Phase 6 — recruitment parity:** extract the current Lead/Job behavior into
   the recruitment adapter without changing candidate-facing behavior, and
   prove a generic flow has no recruitment rows, imports, requests, or copy.
3. **Phase 7 — Release B authority fence:** attach active-generation/capability
   guards to every producer, worker, reconciler, Socket.IO room, outbound
   dispatch, and inbound identity path; only then consider the first
   `runtime_ready=true` pack and activation.

---

## 2. Near-term priorities

These are **observations from the codebase**, not committed commitments. Treat
as candidate work items; confirm with the owner before scheduling.

1. **Complete the protected Phase 5–7 activation gates** above without
   weakening the dormant fail-closed boundary.
2. **Decide logout-on-browser-close behavior** — product call (K-4).
3. ~~**Investigate the open `lead_stage` PATCH issue**~~ — done 2026-09-21; it was
   a real concurrency guard bypass, now fixed (K-6).
4. ~~**Tighten domain exception coverage**~~ — done 2026-09-21; see K-9.
   Every router and the conversation-messaging composition root now raise
   domain errors.
5. **Zalo OA path hardening** — the OA integration is newer than the Bot
   Platform path; load-test + golden-case before promoting to primary.

---

## 3. Known Issues / Tech Debt

> These document **current state only**. Do NOT fix them as part of a docs
> change — they are listed so contributors and operators know what they're
> walking into. Each item includes the file/identifier to grep for.

### K-1. `backend/Makefile` has unmerged git conflict markers — RESOLVED
- **Status:** resolved — the repro grep over `backend/Makefile` returns no
  conflict markers at current HEAD.

### K-2. Two Alembic revision IDs exceed the `VARCHAR(32)` limit — RESOLVED
- **Status:** resolved — the baseline migration widens
  `alembic_version.version_num` to `VARCHAR(128)`
  (`backend/alembic/versions/0001_baseline.py`), `0005` was renamed to a
  short revision, and current descriptive IDs (up to 43 chars) are within
  the widened column and deploy cleanly.

### K-3. Test Redis port mismatch (6380 vs 6382) — RESOLVED
- **Status:** resolved, but the earlier "resolved" note here was itself wrong:
  at that HEAD, `docs/code-standards.md` still pinned
  `REDIS_URL=redis://localhost:6380/0` in its documented test command and
  `docs/troubleshooting/README.md` named `redis://localhost:6379/0` as the dev
  default. Both were corrected 2026-09-21.
- The real finding: the unit suite needs **no Redis at all**. `tests/conftest.py`
  replaces the Redis singletons with a no-op double, which is why the
  `backend-unit` CI job runs a bare `pytest -m "not integration"` with no env
  vars. The documented `REDIS_URL` prefix was vestigial.
- Ports in use: dev `:6382` (host, per `docker-compose.dev.yml` — 6379 belongs
  to a sibling project), prod `:6379` inside the compose network.

### K-4. Logout-on-browser-close is undecided (product call)
- **Current behavior:** JWT access (60 min) + refresh (14 day) tokens are
  stored in **`localStorage`** under `RaStore.auth.*`. `checkAuth` decodes the
  JWT locally and silently calls `refreshOnce()` before forcing re-login when
  the access token is near expiry.
- **Consequence:** users stay logged in across browser restarts for up to 14
  days (or until `token_version` is bumped by a password change).
- **Open question:** if session-scoped persistence is desired (clear on
  browser close), that requires moving tokens to `sessionStorage` (with the
  trade-off that refresh-on-reload no longer works) — a **product decision**,
  not a bug.

### K-5. Dead Supabase CI in `frontend/.github/workflows/deploy.yml` — RESOLVED
- **Status:** resolved — the inherited Atomic CRM workflow tree
  (`frontend/.github/`, both `check.yml` and `deploy.yml`) was removed.
  GitHub only reads repo-root `.github/workflows/`, so these files never ran
  for this repository; `make release-check` covers every gate they provided.

### K-6. `lead_stage` PATCH dropped the concurrency guard — RESOLVED
- **Diagnosed and fixed 2026-09-21.** Root cause: in `update_lead`
  (`app/api/leads.py`), a payload carrying `lead_stage` **and** other fields runs
  `set_stage` — which advances the row version — and then discarded the caller's
  `version` via `changes.pop("version", None)`.
- **Impact:** with no `version` in `changes`, `LeadService.update` takes its
  "trusted internal caller" branch, which never calls `optimistic_apply`. So the
  remaining fields were written with **no** optimistic-concurrency check, and a
  concurrent edit was silently lost (lost update).
- **Proof:** `LeadService.update(lead, {...})` with no `version` makes **0**
  `optimistic_apply` calls and mutates + commits directly; the handler was
  observed handing `{'name': 'edited'}` (no `version`) to the second write.
- **Fix:** re-arm the guard with the version `set_stage` just produced —
  `changes["version"] = lead.version`.
- **Regression test:** `backend/tests/test_lead_update_concurrency.py` — fails
  with `KeyError: 'version'` against the old behaviour, passes now.
- **Blast radius:** latent. The frontend never PATCHes `lead_stage` (it reads the
  field for display and reporting only), so no UI symptom surfaced; any client
  using the documented PATCH contract could have hit it.

### K-7. Legacy / dead code in frontend — RESOLVED
- **Status:** resolved — `@radix-ui/react-navigation-menu` is no longer in
  `frontend/package.json`.

### K-8. No backend CI — RESOLVED
- **Status:** resolved — repo-root `make release-check` runs backend unit
  (ruff + pytest), the backend integration suite, frontend quality, functional
  E2E, and the release gate, and `make deploy` refuses to build or push an image
  until it passes. (Originally resolved through GitHub Actions; the workflows
  were removed on 2026-09-26 for local-only gating — see K-13.)

### K-9. Domain exception coverage partial — RESOLVED
- **Status:** resolved (2026-09-21). The scope was understated: **12 routers, 64
  `raise HTTPException` sites** (not "~8 routers").
- `app/shared/domain/errors.py` now has a single framework-free `DomainError`
  base; each subclass owns its `status_code` and optional response `headers`,
  and `detail` carries the exact JSON payload. Added `BadRequestError` (400),
  `UnauthorizedError` (401, adds `WWW-Authenticate: Bearer`), `GoneError` (410),
  `ValidationError` (422) and `RateLimitedError` (429) to close the gaps the old
  `_STATUS_MAP` could not express.
- `app/core/errors.py` registers one handler against `DomainError` — Starlette
  resolves by MRO, so a future error class cannot be silently forgotten.
- Converted 64 router sites plus 2 in `app/composition/conversation_messaging.py`.
  `grep -rn "raise HTTPException" app/` now returns only `app/core/ratelimit.py`
  (2 sites), which is the sanctioned internal exception.
- **Contract parity proven:** every status code, `detail` payload (including the
  dict `{"errors": [...]}` 422 bodies and the runtime 409-vs-400 branch in
  `knowledge.py`) and header is byte-identical. Unit suite 2312 passed.
- Test fallout fixed: 4 fixtures built a bare `FastAPI()` without
  `register_domain_exception_handlers`, and 4 modules asserted
  `pytest.raises(HTTPException)` on direct dependency calls. Both patterns now
  use the domain errors.
- **Behaviour delta to note:** `/auth/login` and `/auth/refresh` 401s now carry
  `WWW-Authenticate: Bearer`, which they previously omitted. Status and body are
  unchanged; RFC 7235 requires a challenge on 401.

### K-10. Malformed character data in some conversation messages
- **Symptom:** the recruiter inbox can render the replacement character (`�`)
  in message text supplied by upstream data.
- **Scope:** the frontend intentionally renders the received message content
  unchanged so the source issue remains observable; it must not normalize or
  hide the character during presentation.
- **Owner action:** trace the affected records through the Zalo ingestion and
  storage pipeline, capture the original payload encoding, and repair data at
  the source with a separately scoped migration or remediation plan.

### K-11. Web-chat 500 responses echo raw exception text
- **Where:** `app/composition/conversation_messaging.py`, in
  `run_inline_web_chat_turn`.
- **Current behavior:** a failure inside `run_turn` is re-raised as a 500 whose
  `detail` is the raw `str(exc)`, deliberately bypassing the catch-all handler
  in `main.py` that returns a generic Vietnamese 500.
- **Risk:** internal exception text reaches the client on the admin-only
  web-chat trial path. Low exposure (admin-gated), but it is an
  information-disclosure smell.
- **Note:** the K-9 conversion preserved this behavior exactly rather than
  silently changing the contract. Collapsing it to the generic message is a
  small, separate, user-visible decision.
- **Owner action:** confirm whether the raw detail is still wanted for
  debugging; if not, delete the `except` and let the catch-all handle it.

### K-12. Frontend `react-refresh/only-export-components` warnings (16)
- **Where:** 9 component modules under `frontend/src/components/`.
- **Status:** deliberately tolerated. `eslint.config.js` sets the rule to
  `warn` (with `allowConstantExport`), and `release-check` runs a bare
  `npm run lint` with no `--max-warnings`, so warnings never fail the gate.
- **Impact:** Fast Refresh degrades to a full reload while editing those files.
  Development-time only; no runtime or production effect.
- **Owner action:** only worth doing alongside real work on those modules —
  it means extracting the non-component exports into sibling modules and
  updating every importer.

### K-13. GitHub Actions removed — local-only gating
- **Decided:** 2026-09-26 (operator).
- **What:** `.github/workflows/quality-gates.yml` and
  `.github/workflows/openwiki-update.yml` are deleted. `release-check` no longer
  requires a green CI run for the commit under release; it runs every lane on
  the deploying machine instead. The gate list itself is unchanged.
- **Why:** deploys were already manual, so the workflows duplicated work and
  added a hard external dependency — a dead `gh` token, an account billing
  block, or a missing run all blocked a release that the local lanes could have
  cleared in the same time. They cost more than they caught.
- **Trade-off accepted:** a release now has no third-party record of the gates
  having passed. `make deploy` still aborts on the first failing lane, and the
  blue/green smoke turn + turn-pipeline gate remain the production-side proof.
- **OpenWiki (superseded 2026-09-27):** the generated index, the
  `make openwiki` target, `.openwikiignore` and the AGENTS/CLAUDE pointers were
  removed — nothing consumed the index, and it had drifted (its brief described a
  different product). Source code, tests and `docs/` are the only context now.

### K-14. Repowise adopted as the agent-facing codebase index

- **Decided:** 2026-09-27 (operator).
- **What:** repowise (uv-tool CLI) indexes the repo for agents and serves it over
  MCP (`.mcp.json`, gitignored) with a managed pointer in `.claude/CLAUDE.md`; the
  generated `.repowise/` store is gitignored and refreshed by a repowise post-commit
  hook. OpenWiki removal (K-13) is final; its `openwiki` skill remains installed
  globally and uninstalled only affects other projects.
- **Why:** the removed OpenWiki index was never consumed and had drifted; repowise
  is deterministic and keyless at its core (no paid key on this machine), refreshes
  incrementally (`repowise update`), and its analysis needs no LLM spend.
- **Trade-off accepted:** another generated store on disk (~40 MB) plus a git hook;
  wiki prose is structural only until a provider key is configured.

---

## 4. Deferred / out of scope

- **External APM** (Sentry / Datadog / OpenTelemetry) — not wired; structured
  JSON logs + `/metrics` + `/health/queue` are the current observability
  surface. Adding APM is a real cost on a 2-vCPU droplet; defer until needed.
- **Multi-channel** (SMS, WhatsApp, Facebook) — explicitly out of scope; Zalo
  is the sole channel.
- **Public signup** — users are admin-provisioned; `signUp` is disabled in
  the client dataProvider.
- **Mobile native apps** — the console is a responsive web SPA with a mobile
  layout variant only.
