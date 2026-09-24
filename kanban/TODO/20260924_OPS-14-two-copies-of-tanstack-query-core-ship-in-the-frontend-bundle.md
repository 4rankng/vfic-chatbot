---
id: OPS-14
title: "Two copies of @tanstack/query-core ship in the frontend bundle"
severity: medium
area: ops
labels: [ops, performance]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# OPS-14 — Two copies of @tanstack/query-core ship in the frontend bundle

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, performance

**Trạng thái:** TODO

## Problem

`frontend/package.json` pins `@tanstack/query-core` exactly while floating `@tanstack/react-query` on a caret range, so npm resolves a nested second copy of the query core. `package-lock.json` is what CI and the Docker build install from, so the skew ships.

## Evidence

- `frontend/package.json:33` — `"@tanstack/query-core": "5.90.20"` pinned exactly; `:34` — `"@tanstack/react-query": "^5.90.21"` floating.
- `frontend/package-lock.json:6304-6307` resolves root `@tanstack/query-core@5.90.20`; `:6360-6364` resolves a **nested** `node_modules/@tanstack/react-query/node_modules/@tanstack/query-core@5.101.0`.
- `frontend/Dockerfile:9` — `npm ci` installs from `package-lock.json`, so the split resolution is what actually ships.
- `TECH.md:23` — the stack already needs aggressive chunking.

## Impact

Two copies of the query core in one bundle means duplicated, version-skewed internals behind a single `QueryClient`: react-query 5.101's core helpers can behave differently from the 5.90.20 that direct-import sites link against, and ~30-60 KB of dead JS ships.

## Suggested fix

Drop the exact pin (or align it to the resolved version) so npm hoists a single `query-core`, and add an assertion to CI that `npm ls @tanstack/query-core` prints one tree. Consider a general dedupe guard for the React/RA/TanStack trio.

## Notes

Merge with DOC-12 — the second JS lockfile in the same tree is the other half of the frontend dependency-resolution problem.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
