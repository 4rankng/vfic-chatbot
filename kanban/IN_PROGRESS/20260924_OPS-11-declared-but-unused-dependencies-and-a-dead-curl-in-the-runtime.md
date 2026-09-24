---
id: OPS-11
title: "Declared-but-unused dependencies and a dead curl in the runtime image"
severity: medium
area: ops
labels: [ops, tech-debt]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# OPS-11 — Declared-but-unused dependencies and a dead curl in the runtime image

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, tech-debt

**Trạng thái:** TODO

## Problem

Five declared backend dependencies have no import anywhere in `backend/app`, `backend/scripts` or `backend/tests`, and `curl` is installed in the runtime image "for healthcheck" although every compose healthcheck uses Python's `urllib.request`.

## Evidence

- `backend/pyproject.toml:6-34` — `langgraph` has zero imports (`TECH.md:36` confirms "manual node topology, not the LangGraph engine"); `sse-starlette` has zero `sse_starlette`/`EventSourceResponse` imports, the SSE channel having been replaced by Socket.IO (`backend/app/services/realtime.py:5-7`, `backend/app/realtime/socketio.py:58-63`).
- `google-api-python-client` and `google-auth-oauthlib` — zero `googleapiclient`/`google.oauth2`/`Flow.` imports; only `google-genai` is used, via `from google import genai` (`backend/app/graph/clients.py:561`).
- `pgvector` (the Python package) — no `from pgvector…` import; vector columns are raw SQL and `backend/app/models/knowledge.py:308-310` stores `embedding` as `Text` ("vector(3072) at DB; only written via raw SQL").
- `backend/Dockerfile:10` installs `curl` for a healthcheck that does not use it — every compose healthcheck is `python -c urllib.request` (`backend/docker-compose.yml:51,69,101`).
- `backend/Caddyfile.template:34-38` — the `/realtime/*` handler is the only vestige of the removed SSE path.

## Impact

A larger image (curl plus four unused SDKs, including `google-api-python-client`'s large transitive tree), a larger attack surface, and four more unpinned packages that can break a build for no benefit. `sse-starlette` and `langgraph` also mislead readers of `backend/pyproject.toml` about the architecture.

## Suggested fix

Delete `langgraph`, `sse-starlette`, `google-api-python-client`, `google-auth-oauthlib` and `pgvector` from `backend/pyproject.toml:6-34`, and drop `curl` from `backend/Dockerfile:10`; remove the `/realtime/*` route from `backend/Caddyfile.template:34-38` if it is truly dead. Verify that `python-socketio`'s requirements still supply the Redis manager bits the realtime layer relies on.

## Notes

The report's dependency-risk table also flags frontend devDeps (`daisyui`, `tldts`, `glob`, `pgsql-ast-parser`) as unused, but marks them **needs verification** (import greps only; configs and Vite plugins were not traced) — verify before deleting. The undeclared `locust` loadtest dependency is likewise a table row, not a numbered finding.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
