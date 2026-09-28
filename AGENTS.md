# AGENTS.md — Ting Ting Engineering Constitution

This is the small, always-loaded contract for coding agents. Do not preload the
whole documentation tree. Identify the task surface, then retrieve only the
instructions and neighboring files needed for that task.

Restored 2026-09-27 (DOC-19) after `65069078` deleted it while the routing file
still sent agents here. The boundary rules, approval-gated path list, secrets
rule, and completion contract below are load-bearing: nothing else in the repo
holds them. `scripts/check-doc-links.mjs`, run by the root `Makefile`
`release-check` gate, fails the build if any path or `make` target named here
disappears — so a routing target that vanishes is loud, not silent.

## Sources of truth

- Repository map: `docs/product/codebase-summary.md`
- Architecture: `docs/architecture/system-architecture.md`
- API reference: `docs/architecture/api.md`
- Code conventions: `docs/development/code-standards.md`
- Testing: `docs/development/testing.md`
- Agent harness and hooks: `docs/architecture/agent-development-kit.md`
- Agent harness (`.claude/`): machine-local and untracked (see `.gitignore`),
  so nothing under it is a source of truth — every durable rule lives in the
  tracked sources above.
- Completion record: `standards/agent-completion-checklist.md`

For backend, frontend, security, performance, deployment, or bot work, load the
matching source above or the task-routing source below. Do not retrieve unrelated
instructions "just in case." Project instructions override global instructions.

## Non-negotiable boundaries

- API transport belongs in `backend/app/api/`. Framework-free policy and value
  contracts belong in each layer slice's `domain/`, orchestration and ports in
  its `application/`, and shared cross-slice workflows in
  `backend/app/services/`.
- The dependency matrix between those layers is machine-enforced with zero
  exceptions by `backend/tests/test_architecture_boundaries.py`. Read it before
  adding a cross-layer import; it fails `make release-check` when violated.
- Bot-turn behavior belongs in `backend/app/graph/`. `runner.py` drives the
  turn; the stage modules beside it — `backend/app/graph/router.py`,
  `backend/app/graph/prefetch.py`, `backend/app/graph/progressive.py`,
  `backend/app/graph/context.py`, `backend/app/graph/dispatch.py`,
  `backend/app/graph/grounding.py` — hold one stage each and depend on
  Protocols from `backend/app/graph/ports.py`. Wire concrete dependencies in
  `backend/app/graph/factories.py` and `backend/app/composition/`, never inside
  a domain or application module.
- Conversation orchestration belongs in `backend/app/services/conversation/`.
  `backend/app/services/conversation/service.py` is the entry point;
  `backend/app/services/conversation/reconcile_queries.py` holds the reconcile
  SQL and `backend/app/services/conversation/recruiter_receipts.py` the
  recruiter receipt writes, so `reconcile.py` and `recruiter_path.py` stay
  orchestration-only.
- Models mirror the hand-written Alembic schema in `backend/alembic/versions/`;
  they do not generate migrations.
- Frontend dependency direction is `atomic-crm` → `admin` → `ui`; product code
  belongs in `frontend/src/components/atomic-crm/`.
- Keep I/O async, avoid raw SQL outside Alembic and circular imports, and
  offload blocking crypto.
- LLM calls go through `backend/app/graph/clients.py`.
- Use structured logging through `backend/app/core/logging.py`; never log
  secrets, PII, or message content.
- Preserve public contracts and unrelated user changes unless approved scope says
  otherwise. Never add fake production behavior or weaken checks.

## Approval required

Stop and ask before:

- creating or editing anything under `backend/alembic/versions/`;
- changing webhooks, integrations, auth/JWT/CORS/rate limits, or security controls;
- making incompatible API or database-schema changes;
- changing bot prompts, personas, safety, grounding, or tool definitions;
- adding, removing, or upgrading dependencies;
- changing deployment files, deploying, or introducing a cross-cutting pattern.

Never edit secrets (`.env`, private keys, credentials). Protected paths include
`backend/app/core/config.py`, `backend/app/core/security.py`,
`backend/app/core/ratelimit.py`, `backend/app/api/webhooks.py`,
`backend/app/api/auth_dependencies.py`, the policy files under
`backend/app/prompts/`, `frontend/src/index.css`, the dependency manifests
(`backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`), the
deployment files (`backend/docker-compose.yml`), and the root, backend, and
frontend `Makefile`s. See `docs/architecture/agent-development-kit.md` for hook
behavior.

## Scoped workflow

1. Inspect `git status`, relevant neighboring files, and `plans/` for overlap.
2. State artifacts, acceptance criteria, exclusions, and approval gates.
3. Retrieve only task-relevant instructions. Use existing patterns and the
   smallest complete change; prove bug causes and add regression tests.
4. Run the narrowest relevant check, broadening only for shared behavior or
   contracts. Never hide failures. If you change what this file or the routed
   documents point at, run `node scripts/check-doc-links.mjs` before finishing.
5. Copy `standards/agent-completion-checklist.md` to
   `plans/reports/<date>-<slug>-completion.md` and fill every gate with
   `PASS`, `N/A`, or `BLOCKED` plus evidence before declaring completion.
6. Update docs only for user-visible behavior, setup, commands, architecture,
   security posture, public contracts, or durable maintainer decisions.

Do not deploy, commit, push, merge, open a PR, or create a branch unless asked.
When asked to commit, work directly on `main` per the repository workflow.

## Task routing

- Implementation: `docs/development/code-standards.md`
- Verification: `standards/review-checklist.md`
- Dev-environment QA: `standards/agent-completion-checklist.md` (record only)
- UI/UX design problems: `frontend/AGENTS.md` → "UI/UX Component Sourcing".
  Consult the Untitled UI and Tailkit MCPs before hand-writing markup; Tailkit
  drops in today, Untitled UI React components await the Phase 3 toolchain work.
- Bot diagnosis: `docs/troubleshooting/chatbot-response-path.html`
- Deployment: read `docs/ops/deployment-guide.md` in full, then obtain approval.
  `make deploy` is blue/green + smoke-gated (zero-downtime Caddy flip); the old
  color serves until the new color is healthy and passes
  `backend/scripts/smoke_turn.py`. `make -C backend rollback` flips back to the
  previous color/tag without a rebuild.

Use `standards/definition-of-done.md` and `standards/review-checklist.md` only
when their detailed gates apply to the task.
