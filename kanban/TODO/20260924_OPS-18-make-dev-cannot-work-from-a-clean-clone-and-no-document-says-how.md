---
id: OPS-18
title: "make dev cannot work from a clean clone and no document says how to bootstrap"
severity: medium
area: ops
labels: [ops, documentation]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# OPS-18 — make dev cannot work from a clean clone and no document says how to bootstrap

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, documentation

**Trạng thái:** TODO

## Problem

There is no root `README.md`, and no document contains a `python -m venv` or `npm ci` step. `make dev` prints "Starting VFIC dev environment" and then dies twice — once because `backend/.venv/bin/python` does not exist, and once because `frontend/node_modules` is missing.

## Evidence

- No root `README.md` exists; grepping `docs/`, `TECH.md` and `AGENTS.md` for `python -m venv|pip install -e|npm ci|npm install` returns only architecture prose and `make dev` usage.
- `backend/Makefile:12` — `PY := ./.venv/bin/python`; the `dev` recipe hard-fails at `$(PY) -m uvicorn` (`:82`) and spawns `(cd ../frontend && exec npm run dev …)` (`:85`), which fails without `frontend/node_modules`.
- `backend/Makefile:33-34` — the `db` target degrades silently via `|| echo`, so the missing venv is hidden there and only surfaces later.
- `docs/qa-runbook.md:31-32` claims `make dev` seeds the DB, and `docs/troubleshooting/README.md:67` tells users to change `PORT` — neither is true (see OPS-12, OPS-19).

## Impact

A new engineer cannot get a working stack in one command, and the failure messages (`/bin/sh: ./.venv/bin/python: No such file`) point at the Makefile rather than at the missing bootstrap.

## Suggested fix

Add a `bootstrap` (or `setup`) target — `python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -e 'backend/.[dev]'` plus `npm ci --prefix frontend` — make `dev` depend on it guarded by `test -d`, and write a short root `README.md` whose first heading is the one-command path. Also fix `docs/qa-runbook.md:31-32` (seeding) and `docs/troubleshooting/README.md:67`.

## Notes

Merge with OPS-13 (the bootstrap target is where the 3.12 venv gets pinned), OPS-19 (the port override) and DOC-10 (missing root README).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
