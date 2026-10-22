# Agent Completion Checklist — dependabot Oct22 dependency fixes

## Task record

- Task: `fix(deps): dependabot Oct22` — clear the 15 open Dependabot alerts
  (1 critical + 5 high + 8 medium/low + 1 low) plus 1 additional Python CVE
  found via pip-audit, via targeted lockfile/override bumps only.
- Scope: `frontend/package.json` (1 override line), `frontend/package-lock.json`,
  `backend/uv.lock`. No application source, no framework major bumps.
- Files changed: `frontend/package.json`, `frontend/package-lock.json`,
  `backend/uv.lock`, this report.
- Instructions retrieved: root `AGENTS.md` (constitution + completion-checklist
  workflow); in-session task brief (fix + gates + commit + push, LOCAL only).
- Approval required: No — user directive in-session.
- Approval evidence: user message "fix + tests + commit + push … Commit:
  `fix(deps): dependabot Oct22 — <gói> (1 critical + 5 high → 0)` + PUSH".

## Alert-to-fix mapping (Dependabot open set, verified via `gh api` = 15)

| Alert | Package | Fix applied | Status |
|---|---|---|---|
| #251 critical | proxy-addr 2.0.7 | → 2.0.8 (express `^2.0.7` in-range) | FIXED |
| #252,#256 high; #261,#262 medium | @modelcontextprotocol/sdk 1.26.0 | → 1.32.1 (shadcn `^1.17.2` in-range) | FIXED |
| #259 high; #257,#258 medium | vite 8.3.1 | → 8.3.5 (`^8.3.1` in-range; also launch-editor advisories) | FIXED |
| #254,#255 high; #253 low | aiohttp 3.14.3 (pip) | → 3.14.5 (`uv lock --upgrade-package`) | FIXED |
| #260 medium | hono 4.13.7 | → 4.13.13 (MCP SDK `^4` in-range) | FIXED |
| #250 medium | postcss-selector-parser 6.0.10 | → 7.1.7 via new override `^7.1.6` (`@tailwindcss/typography` pins `6.0.10` exactly) | FIXED |
| #249 medium | mako 1.3.12 (pip) | → 1.4.3 (alembic `Mako>=1.2.2` in-range) | FIXED |
| #194 medium | decode-uri-component ≤0.4.2 | only 0.5.0 is patched, but 0.5.0 is ESM-only; `query-string@7` (required by `ra-core` named imports) calls it CJS-style → runtime crash. Verified experimentally (v9/v10 override → `MISSING_EXPORT parse/stringify` at build, `decodeComponent is not a function` at runtime). | BLOCKED upstream |

Extra beyond the 15: certifi 2026.6.17 → 2026.10.19 (PYSEC-2026-4320), found by
`uvx pip-audit` over `uv export --frozen --no-dev`; Dependabot had no alert yet.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | 15 alerts → 14 fixed incl. all 1 critical + 5 high; remaining #194 is upstream-blocked with repro evidence (see mapping table) |
| Diff is limited to the approved scope | PASS | `git diff --stat`: 3 tracked files (2 lockfiles + 1 override line); lock changes are the security set plus in-range transitive resolutions (rolldown 1.2.15, postcss 8.5.31, nanoid 3.3.20) |
| Protected operations were avoided or approved | PASS | No deploy/merge/PR/branch; commit+push explicitly requested |
| Focused tests/checks pass | PASS | `npm run test:unit:app -- --run`: 131 files, 1123/1123 passed; `backend/.venv/bin/python -m pytest -q -m "not integration" -p no:randomly`: 4164 passed, 28 skipped, 0 errors |
| Broader regression tests pass when shared behavior changed | PASS | Full app vitest project (browser mode, chromium) and full backend unit lane re-run after each lock change; both green |
| Lint passes for affected code | N/A | No application source changed; only JSON manifests/lockfiles |
| Type checking passes for affected code | PASS | `npm run build` runs `tsc` first — clean |
| Build/import validation passes for affected code | PASS | `npm run build` (tsc + vite 8.3.5 + PWA) OK; typography `@plugin` exercises postcss-selector-parser 7.1.7 in the CSS pipeline; vitest browser suite exercises vite dev-transform path |
| Security and privacy impact reviewed | PASS | Advisory-by-advisory mapping above; `npm audit --omit=dev` = 0 high/critical (4 moderate = blocked #194 chain); `npm audit --omit=dev --audit-level=high` exit 0 (Makefile gate); `uvx pip-audit` over prod export: "No known vulnerabilities found"; local `.env` copied from main checkout is gitignored (`backend/.gitignore:9`) and never staged |
| Performance and async-I/O impact reviewed | N/A | Dependency pins only; no async or hot-path code changes |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes |
| Error handling and compatibility reviewed | PASS | decode-uri-component 0.5.0 and query-string 9/10 overrides were tested and REVERTED after build/runtime breakage; postcss-selector-parser 7.1.7 validated by build + 1123 browser tests |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets … resolve"; no routed docs changed |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff` contains none |
| Final `git diff --check` passes | PASS | clean |
| Final `git status --short` reviewed | PASS | `M backend/uv.lock`, `M frontend/package-lock.json`, `M frontend/package.json` + this new report; `.env`/`.venv`/`dist` untracked-but-ignored |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - #194 decode-uri-component (moderate, runtime): stays open until react-admin
    `ra-core` migrates off `query-string@7` (needs named CJS exports). A
    follow-up should re-test `query-string` override once ra-core supports ≥9.
  - `npm audit` (dev-inclusive) still lists the braces GHSA-vfj7-8cjw-p6xm
    chain (braces ≤3.0.3, no patched release; dev-only via shadcn/ts-morph) and
    vitest ≤4.1.11 moderates — neither set has Dependabot alerts in this repo
    and neither is in the 15-alert target; left untouched deliberately.
  - Backend integration digest tests need `DATABASE_URL` pointing at
    127.0.0.1:5443 (local `.env`); documented in `docker-compose.dev.yml`.
