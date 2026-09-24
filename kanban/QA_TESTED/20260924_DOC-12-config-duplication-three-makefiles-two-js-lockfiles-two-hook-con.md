---
id: DOC-12
title: "Config duplication — three Makefiles, two JS lockfiles, two hook configs and rules duplicated across two trees"
severity: medium
area: docs
labels: [documentation, tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# DOC-12 — Config duplication — three Makefiles, two JS lockfiles, two hook configs and rules duplicated across two trees

**Severity:** medium · **Area:** docs · **Effort:** M · **Labels:** documentation, tech-debt

**Trạng thái:** QA_TESTED

## Problem

Every shared concern in the build has at least two authoritative files: three Makefiles (one lowercase), two JS lockfiles for one package-manager boundary, two compose files plus Vite dev proxies, a tracked Caddy template against a generated Caddy file, two hook configs, and code-convention rules restated across `standards/` and `docs/`.

## Evidence

- Makefiles ×3 — `Makefile` (7.9 KB root), `backend/Makefile` (12.5 KB) and `frontend/makefile` (**lowercase**, 2.3 KB); root `deploy` shells into the other two, so one release-flow edit means three files, and `TECH.md`/`AGENTS.md` mark all three approval-gated.
- Lockfiles ×2 for the same boundary — `frontend/package-lock.json` (568.5 KB) and `frontend/pnpm-lock.yaml` (370.4 KB) are both tracked with `.npmrc` and `.nvmrc` present, while `TECH.md:31` says "npm + `legacy-peer-deps`": ~940 KB of churn and an ambiguous install path.
- Caddy — `backend/Caddyfile.template` is tracked while `backend/Caddyfile` is generated at deploy and mounted at `backend/docker-compose.yml:224`, so a clean `docker compose up` in `backend/` cannot mount the volume, and two docs call the generated file the real one.
- Rules duplicated — `standards/coding-style.md:4-5` versus `docs/code-standards.md` (15.8 KB), both presented as "Code conventions" by `AGENTS.md:11` and `TECH.md` §5, with the same content restated a third time in `standards/review-checklist.md`; the overlap has already produced a contradiction (virtuoso/virtua — DOC-03).
- Hook config ×2 — `.claude/settings.json` versus `.claude/hooks/hooks.json`, including the doubled `UserPromptSubmit` block (DOC-05).

## Impact

Every release-flow or convention change has to be made in two or three places, and the duplicates have already diverged in ways that mislead readers; the second lockfile means two different dependency resolutions can be claimed for one project.

## Suggested fix

Collapse each pair to one authoritative file with the other holding only a pointer: keep `backend/Makefile` plus a thin root delegator (delete `frontend/makefile` or make it a one-line delegator); commit one JS lockfile (`pnpm-lock.yaml` **or** `package-lock.json`, per `TECH.md:31` → npm); make `AGENTS.md:11` point at exactly one code-convention document; and delete the redundant hook manifest if `settings.json` is the live file.

## Notes

Merge with DOC-05 (hooks), OPS-05 (lockfile policy) and OPS-19 (Makefile variable forwarding).

## Evidence log

- config duplication reduced: hooks collapsed to settings.json, docs/agent-development-kit.md records one configuration authority
- verified: docs/agent-development-kit.md rewritten with the hooks layer + verification section
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
