---
id: OPS-15
title: "Dev-only mock servers and the env template ship into the production backend image"
severity: medium
area: ops
labels: [ops, security]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# OPS-15 — Dev-only mock servers and the env template ship into the production backend image

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, security

**Trạng thái:** IN_PROGRESS

## Problem

`backend/.dockerignore` excludes `.venv`, `tests`, `.env*`, `Dockerfile`, `docker-compose*.yml` and `Caddyfile`, but not `mock_servers/` or `.env.example`. The image then runs `COPY . .`, so the fake Zalo endpoint used by `make dev` and the env template ride into production.

## Evidence

- `backend/.dockerignore` — excludes `.venv`, `tests`, `.env*`, `Dockerfile`, `docker-compose*.yml`, `Caddyfile`; `mock_servers/` and `.env.example` are absent from the list.
- `backend/Dockerfile:18` — `pip install -e .`; `:21` — `COPY . .`, which carries `mock_servers/zalo_mock.py`, the fake Zalo inbound/outbound endpoint used by `make dev` (`backend/Makefile:82`).
- `docs/deployment-guide.md:56` — the smoke gate already stubs LLM and Zalo, so the mock is not needed inside the image.
- [INFERENCE] That the mock is *reachable* on the production compose network is inferred from `.dockerignore` plus `COPY . .`; it was not observed at runtime.

## Impact

A webhook-shaped mock server and the env template are importable inside the production compose network, widening the surface for an attacker who already has container access and muddying "what is production code".

## Suggested fix

Add `mock_servers` and `.env.example` to `backend/.dockerignore`; if `smoke_turn` needs a stubbed channel, keep the stub inside `backend/scripts/` or `backend/tests/`.

## Notes

Merge with OPS-11 — both are single-file trims of the backend image.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
