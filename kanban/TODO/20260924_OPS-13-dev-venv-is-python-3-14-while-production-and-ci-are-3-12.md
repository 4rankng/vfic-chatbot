---
id: OPS-13
title: "Dev venv is Python 3.14 while production and CI are 3.12"
severity: medium
area: ops
labels: [ops, testing]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# OPS-13 — Dev venv is Python 3.14 while production and CI are 3.12

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, testing

**Trạng thái:** TODO

## Problem

The local virtualenv resolves to Python 3.14 while the image and both CI jobs pin 3.12, and `requires-python` has no upper bound. The Makefile's `dev`/`db` targets and `release-check` therefore exercise an interpreter no deployed artefact uses.

## Evidence

- `backend/.venv/lib/python3.14/site-packages/` and `__pycache__/*.cpython-314.pyc` throughout `backend/alembic/versions/`, `backend/scripts/` and `backend/app/`, versus `backend/Dockerfile:2` `FROM python:3.12-slim` and `python-version: "3.12"` in both CI jobs (`.github/workflows/quality-gates.yml`).
- `backend/pyproject.toml:4` — `requires-python = ">=3.12"` with no upper bound; `backend/uv.lock:3-7` carries resolution markers for `<3.13`, `3.13.*` and `>=3.14`.
- `backend/pyproject.toml:62-64` — the `passlib` `crypt` filter exists precisely because of the 3.12→3.13 stdlib removal, so the version boundary is already load-bearing.
- Concrete bytecode evidence: `backend/alembic/versions/__pycache__/0054_channel_account_projects.cpython-314.pyc`, `backend/app/graph/__pycache__/runner.cpython-314.pyc`, against `[tool.ruff] target-version = "py312"`.

## Impact

Stdlib removals, C-extension differences (`asyncpg`, `cryptography`) and build behaviour mean bugs that reproduce in production can be invisible locally and vice versa; the interpreter that runs the release gate is not the interpreter that runs the code.

## Suggested fix

Pin the dev venv to 3.12 (a `.python-version` for uv/pyenv, or a documented `python3.12 -m venv backend/.venv` bootstrap step) and set `requires-python = ">=3.12,<3.13"` in `backend/pyproject.toml:4` unless 3.14 support is intended and tested in CI.

## Notes

Hygiene finding F18 (Python 3.14 bytecode leftovers in a 3.12 project) is covered here — the `__pycache__` directories should be deleted before packaging. Couples with OPS-18, whose bootstrap target is where the 3.12 venv should be created.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
