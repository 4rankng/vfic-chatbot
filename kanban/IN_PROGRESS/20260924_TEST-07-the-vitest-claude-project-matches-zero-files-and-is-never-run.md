---
id: TEST-07
title: "The vitest claude project matches zero files and is never run"
severity: high
area: testing
labels: [testing, tech-debt]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# TEST-07 — The vitest claude project matches zero files and is never run

**Severity:** high · **Area:** testing · **Effort:** S · **Labels:** testing, tech-debt

**Trạng thái:** TODO

## Problem

`vitest.config.ts` declares a second test project whose include glob matches no file in the repository, and neither CI nor the Makefile invokes its npm script. It reads as a working test lane while being dead config that can never pass.

## Evidence

- `frontend/vitest.config.ts:87-90` — project `claude` with `include: [".claude/**/*.test.mjs"]` and a 30 s timeout.
- A repo-wide glob for `**/*.test.mjs` returns nothing, and `frontend/.claude` does not exist; the only `.claude/` is the repo-root agent config, which contains `hooks/*.cjs`, `skills/` and `agents/` but no tests.
- `.github/workflows/quality-gates.yml:138` runs only `npm run test:unit:app`, and `frontend/package.json:9` (`test:unit:claude`) is referenced by neither CI nor the `Makefile`.

## Impact

Vitest exits non-zero on "No test files found" by default, so anyone running `npm run test:unit:claude` gets a red result that looks like a broken suite, and any future hook tests placed at `.claude/**` would silently not run in CI. [INFERRED — the non-zero exit follows from Vitest's default `passWithNoTests: false`; the script was not executed.]

## Suggested fix

Either add `passWithNoTests: true` to the project and wire `npm run test:unit:claude` into the `frontend-quality` job, or delete the project block and the `test:unit:claude` script until the hook tests exist. Do not leave a project that can never pass and never runs.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
