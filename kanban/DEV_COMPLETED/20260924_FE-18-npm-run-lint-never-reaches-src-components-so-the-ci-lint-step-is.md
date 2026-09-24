---
id: FE-18
title: "npm run lint never reaches src/components, so the CI lint step is vacuous"
severity: high
area: testing
labels: [testing, tech-debt]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-18 — npm run lint never reaches src/components, so the CI lint step is vacuous

**Severity:** high · **Area:** testing · **Effort:** S · **Labels:** testing, tech-debt

**Trạng thái:** DEV_COMPLETED

## Problem

The lint script is `eslint **/*.{mjs,ts,tsx} --no-warn-ignored` — unquoted — so `/bin/sh` expands `**` as `*`. ESLint therefore receives only the top-level files and never reaches `src/components/**`, which is essentially the whole application. `npm run lint` exits 0 regardless of what the code does, and the `frontend-quality` CI job's Lint step has been enforcing nothing.

## Evidence

- `frontend/package.json:9` — `"lint": "eslint **/*.{mjs,ts,tsx} --no-warn-ignored"`, unquoted.
- `sh -c 'printf "%s\n" **/*.{mjs,ts,tsx} | wc -l'` returns **11** files (App.tsx, main.tsx, App.installation.test.tsx, vite-env.d.ts, e2e/*.ts), while `npx eslint "**/*.{mjs,ts,tsx}" --no-warn-ignored` lints **457**.
- `.github/workflows/quality-gates.yml` runs `npm run lint` in the `frontend-quality` job, so the vacuous glob is what CI executes.
- Surfaced by FE-08: adding `src/components/atomic-crm/**` to the `no-explicit-any` scope had no observable effect until the glob was quoted.

## Impact

Three quarters of the codebase has had no lint enforcement at all, and the CI signal that was supposed to catch it reported success. A rule change to `eslint.config.js` is unverifiable through the script that runs it.

## Suggested fix

Quote the glob: `eslint "**/*.{mjs,ts,tsx}" --no-warn-ignored`. Measured at the time of the fix, the tree has only 3 errors (in two files being edited concurrently) and 15 warnings, so the corrected script is immediately green — this is a one-line change, not a backlog.

## Evidence log

- 8d8740d1 — `npm run lint` glob quoted (also on `lint:apply`). It previously lints 11 top-level files and never reached `src/components/**`, so the script exited 0 regardless of the code and the CI Lint step enforced nothing. It now lints 457 files with 0 errors.
- The gate is proven real, not assumed: the newly-live rule immediately caught a genuine `react-hooks/rules-of-hooks` violation (a conditional `useTranslate` introduced during FE-07), which was fixed.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
