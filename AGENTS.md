# AGENTS.md — Ting Ting Engineering Constitution

This is the small, always-loaded contract for coding agents. Do not preload the
whole documentation tree. Identify the task surface, then retrieve only the
instructions and neighboring files needed for that task.

## Sources of truth

- System map and stack: `TECH.md`
- Repository map: `docs/codebase-summary.md`
- Architecture: `docs/system-architecture.md`
- Code conventions: `docs/code-standards.md`
- Testing: `docs/testing.md`
- Completion record: `standards/agent-completion-checklist.md`

For backend, frontend, security, performance, deployment, or bot work, load the
matching source above or the task-routing source below. Do not retrieve unrelated
instructions "just in case." Project instructions override global instructions.

## Non-negotiable boundaries

- API transport belongs in `backend/app/api/`; business logic belongs in
  `backend/app/services/`.
- Bot-turn behavior belongs in `backend/app/graph/` and depends on Protocols from
  `graph/ports.py`; wire concrete dependencies in `factories.py`.
- Models mirror the hand-written Alembic schema; they do not generate migrations.
- Frontend dependency direction is `atomic-crm` → `admin` → `ui`; product code
  belongs in `frontend/src/components/atomic-crm/`.
- Keep I/O async, avoid raw SQL and circular imports, and offload blocking crypto.
- LLM calls go through `backend/app/graph/clients.py`.
- Use structured logging; never log secrets, PII, or message content.
- Preserve public contracts and unrelated user changes unless approved scope says
  otherwise. Never add fake production behavior or weaken checks.

## Approval required

Stop and ask before:

- creating or editing `backend/alembic/versions/*.py`;
- changing webhooks, integrations, auth/JWT/CORS/rate limits, or security controls;
- making incompatible API or database-schema changes;
- changing bot prompts, personas, safety, grounding, or tool definitions;
- adding, removing, or upgrading dependencies;
- changing deployment files, deploying, or introducing a cross-cutting pattern.

Never edit secrets (`.env`, private keys, credentials). Protected paths include
`backend/app/core/{config,security,ratelimit}.py`,
`backend/app/api/{webhooks,auth_dependencies}.py`, bot policy files,
`frontend/src/index.css`, dependency manifests, deployment files, and root/backend/
frontend `Makefile`s. See `docs/agent-development-kit.md` for hook behavior.

## Scoped workflow

1. Inspect `git status`, relevant neighboring files, and `plans/` for overlap.
2. State artifacts, acceptance criteria, exclusions, and approval gates.
3. Retrieve only task-relevant instructions. Use existing patterns and the
   smallest complete change; prove bug causes and add regression tests.
4. Run the narrowest relevant check, broadening only for shared behavior or
   contracts. Never hide failures.
5. Copy `standards/agent-completion-checklist.md` to
   `plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` and fill every gate with
   `PASS`, `N/A`, or `BLOCKED` plus evidence before declaring completion.
6. Update docs only for user-visible behavior, setup, commands, architecture,
   security posture, public contracts, or durable maintainer decisions.

Do not deploy, commit, push, merge, open a PR, or create a branch unless asked.
When asked to commit, work directly on `main` per the repository workflow.

## Task routing

- Implementation: `.claude/skills/ak-cook/SKILL.md`
- Verification: `.claude/skills/ak-debug/SKILL.md`
- Dev-environment QA: `standards/agent-completion-checklist.md` (record only)
- Bot diagnosis: `docs/troubleshooting/chatbot-response-path.html`
- Deployment: read `docs/deployment-guide.md` in full, then obtain approval.
  `make deploy` is blue/green + smoke-gated (zero-downtime Caddy flip); the old
  color serves until the new color is healthy and passes
  `backend/scripts/smoke_turn.py`.
  `make rollback` flips back to the previous color/tag (~1s, no rebuild).

Use `standards/definition-of-done.md` and `standards/review-checklist.md` only
when their detailed gates apply to the task.

<!-- OPENWIKI:START -->

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
