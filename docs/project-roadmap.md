# Project Roadmap

**Last updated:** 2026-07-15
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
  inbox, lead kanban, knowledge base, personas, projects.
- Proactive follow-up worker (6h/24h/46h cadence, Zalo-48h-safe).
- Reconcile worker recovers lost turns after crashes (~3-4 min).
- Auth via JWT (replaces Supabase Auth, decommissioned 2026-06-26) with
  `token_version` revocation.
- Alembic HEAD = `0044_generic_contact_case_kernel` (15 Jul 2026).
- Manual deploy via `make deploy` over SSH (no CI deploys to prod).

Zalo Official Account integration is implemented in the working tree and
documented here; verify maturity before relying on it in prod.

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
  `2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9`),
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

1. **Phase 5 — runtime policy authority:** replace or deliberately capability-
   own the setup persona contract that still serializes disabled recruitment
   keys `hot`, `warm`, and `not_interested`; compose pinned persona/policy/tool
   authority and fence active-KB mutation.
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
2. **Resolve the Makefile conflict markers** so `make dev` is reliable for
   new contributors (see Known Issues K-1).
3. **Fix over-length Alembic revision IDs** so migrations can't fail the
   `VARCHAR(32)` constraint under future tooling (K-2).
4. **Clarify the test Redis expectation** — either stand up a dedicated test
   Redis on 6380 or align the test command with the dev compose port 6382
   (K-3).
5. **Decide logout-on-browser-close behavior** — product call (K-4).
6. **Remove dead Supabase CI** from the frontend workflow (K-5).
7. **Investigate the open `lead_stage` PATCH issue** (K-6).
8. **Tighten domain exception coverage** — some routers still raise raw
   `HTTPException`; convert when touched (code-standards notes this).
9. **Zalo OA path hardening** — the OA integration is newer than the Bot
   Platform path; load-test + golden-case before promoting to primary.

---

## 3. Known Issues / Tech Debt

> These document **current state only**. Do NOT fix them as part of a docs
> change — they are listed so contributors and operators know what they're
> walking into. Each item includes the file/identifier to grep for.

### K-1. `backend/Makefile` has unmerged git conflict markers
- **Symptom:** two `dev` target variants in `backend/Makefile`, separated by
  conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`). Blocks `make dev`
  reliability for fresh checkouts.
- **Repro:** `grep -nE '^(<<<<<<<|=======|>>>>>>>)' backend/Makefile`.
- **Workaround:** resolve manually by keeping the `dev` variant that matches
  the host-uvicorn + workers + mock pattern documented in README.
- **Owner action:** commit a clean resolution.

### K-2. Two Alembic revision IDs exceed the `VARCHAR(32)` limit
- **Revisions affected:**
  - `091e7edc9f76_merge_0013_password_reset_otps_0013_` — **49 chars** (the
    merge head).
  - `0005_remove_knowledge_approval_gate` — **35 chars**.
- **Risk:** Alembic's `revision` column is `VARCHAR(32)`; some tooling paths
  can truncate or reject these IDs. A prior fix (migration `0021`) truncated
  a too-long revision ID to ≤32 chars; the same pattern needs applying here.
- **Owner action:** rename revisions + update `down_revision` chains; or
  document an accepted exception if the limit is no longer enforced.

### K-3. Test Redis port mismatch (6380 vs 6382)
- **Symptom:** local test command pins `REDIS_URL=redis://localhost:6380/0`
  but `backend/docker-compose.dev.yml` exposes Redis on **6382** (6379
  belongs to a sibling payroll project).
- **Implication:** either a dedicated test Redis on 6380 is expected (and
  undocumented), or the test command is stale. Backend tests are pure unit
  (no live Redis per `conftest.py`), so the env var is currently load-bearing
  only for the `Settings()` instantiation path.
- **Owner action:** either stand up a test Redis on 6380 and document it, or
  align the test command with 6382.

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

### K-5. Dead Supabase CI in `frontend/.github/workflows/deploy.yml`
- **Symptom:** `deploy.yml` still defines a `deploy-supabase` job.
- **Context:** Supabase was decommissioned on **2026-06-26**. The job is dead
  template residue inherited from the Atomic CRM template (per
  `frontend/AGENTS.md`).
- **Owner action:** remove the `deploy-supabase` job (and any
  `scripts/supabase-*.mjs` leftovers + stale `Makefile` `supabase-*` targets,
  if still present).

### K-6. Open `lead_stage` PATCH issue
- **Status:** per project memory, an open issue exists with `lead_stage`
  PATCH behavior. Not diagnosed here.
- **Owner action:** reproduce against current HEAD, capture the failing
  request/response, and scope a fix. (Documented to prevent it being
  forgotten — do not assume it is still reproducible without verifying.)

### K-7. Legacy / dead code in frontend
- An orphaned `@radix-ui/react-navigation-menu` sub-package was left after a
  wrapper component was deleted. Low-priority cleanup.

### K-8. No backend CI
- Backend has no `.github/workflows`; deploys are manual `make push` +
  `make deploy` over SSH with ControlMaster multiplexing (~9 sequential SSH
  calls). A backend CI workflow (lint + unit tests on PR) would catch
  regressions like K-1 and K-2 before they land on `main`.

### K-9. Domain exception coverage partial
- `register_domain_exception_handlers` is the canonical error path, but ~8
  routers still raise raw `HTTPException`. Convert when those modules are
  next touched; do not mix styles within one module.

### K-10. Malformed character data in some conversation messages
- **Symptom:** the recruiter inbox can render the replacement character (`�`)
  in message text supplied by upstream data.
- **Scope:** the frontend intentionally renders the received message content
  unchanged so the source issue remains observable; it must not normalize or
  hide the character during presentation.
- **Owner action:** trace the affected records through the Zalo ingestion and
  storage pipeline, capture the original payload encoding, and repair data at
  the source with a separately scoped migration or remediation plan.

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
