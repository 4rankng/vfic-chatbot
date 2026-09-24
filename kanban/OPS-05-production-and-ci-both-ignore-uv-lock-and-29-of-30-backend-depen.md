---
id: OPS-05
title: "Production and CI both ignore uv.lock, and 29 of 30 backend dependencies have no upper bound"
severity: high
area: ops
labels: [ops, reliability]
effort: M
status: todo
found: 2026-09-24
---

# OPS-05 — Production and CI both ignore uv.lock, and 29 of 30 backend dependencies have no upper bound

**Severity:** high · **Area:** ops · **Effort:** M · **Labels:** ops, reliability

## Problem

`backend/Dockerfile` installs with `pip install -e .` and every CI job uses `pip install -e .[dev]`; neither consults `backend/uv.lock`, which has no consumer anywhere in the repo. Only one of the 30 declared backend dependencies carries a cap, so the image that reaches production is whatever PyPI served at build time.

## Evidence

- `backend/Dockerfile:18` — `pip install --upgrade pip && pip install -e .` (no `[dev]`, which is good; no lock, which is not).
- `.github/workflows/quality-gates.yml` — all four backend/frontend jobs run `pip install -e .[dev]` (backend-unit, backend-integration, functional-e2e, release-gate), and the pip cache is keyed on `backend/pyproject.toml`, never on `uv.lock`.
- `backend/uv.lock` — 435 KB / 2468 lines with resolution markers for 3.12/3.13/3.14, but grepping `uv sync|uv lock|--frozen|uv.lock` across `backend/`, `Makefile` and `.github/` returns no consumer.
- `backend/pyproject.toml:6-34` — only `redis>=5.2,<8.0.0` (`:20`) is capped; `fastapi`, `sqlalchemy`, `alembic`, `pydantic`, `langchain-core`, `langchain-openai`, `langgraph`, `httpx` and `rq` are open-ended.
- There is no image-build job in `.github/workflows/quality-gates.yml`, so CI never builds or runs the image it ships.

## Impact

A fresh upstream major (SQLAlchemy 3, FastAPI 1, LangChain 1, Pydantic 3) can land in production without a single code review or CI signal, and `uv.lock` provides a false sense of pinning. The same commit can also build into two different environments, so deploy-time breakage is not reproducible.

## Suggested fix

Pick one story and enforce it: either `uv export --frozen --no-dev -o requirements.txt` in `backend/Dockerfile` plus `uv sync --frozen` in CI (keeping `uv lock --check` in `release-check`), or delete `uv.lock` and add explicit `<N+1` caps to every entry in `backend/pyproject.toml:6-34`. Either way, add an image-build + `/health` + `smoke_turn` job to CI so pin drift is caught before the droplet sees it.

## Notes

Merge with OPS-20 (`release-check` never checks lockfile consistency) and OPS-14 (a lockfile that resolves two copies of one package).

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
