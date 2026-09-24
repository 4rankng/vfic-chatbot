---
id: SEC-04
title: "Rate limiting covers only the four auth endpoints; webhooks and LLM routes are unbounded"
severity: medium
area: security
labels: [security, performance]
effort: M
status: todo
found: 2026-09-24
---

# SEC-04 — Rate limiting covers only the four auth endpoints; webhooks and LLM routes are unbounded

**Severity:** medium · **Area:** security · **Effort:** M · **Labels:** security, performance

## Problem

The only configured limits are on login / forgot-password / reset-password / refresh. Every LLM- or embedding-backed route and all webhook POSTs are unbounded, and the limiter fails open on Redis errors.

## Evidence

- `backend/app/identity/infrastructure/rate_limits.py` — the complete configured surface; `backend/app/api/auth.py:23-28` is its only importer.
- Unbounded expensive routes: `POST /jobs/search` (`backend/app/api/jobs.py:95-105`), `POST /projects/{id}/rag/test` (`api/knowledge.py:216`), `GET /leads/{id}/assist`, `POST /leads/{id}/chatops-actions/*`, `POST /conversations/{id}/web-chat-turn` (`api/conversations.py:408`), and all four webhook POSTs.
- `backend/app/core/ratelimit.py:56-57` fails open on any Redis exception; `:22-28` trusts the first `X-Forwarded-For` hop for bucketing.

## Impact

An authenticated recruiter firing N parallel `/web-chat-turn` or `/jobs/search` requests drains the deployment-wide LLM/embed token lists (`llm_concurrency_limit=8`, `embed_concurrency_limit=6`) and suppresses genuine candidate turns by the configured fail-fast contract.

## Suggested fix

Add an IP limiter on the four webhook routes and a per-user limiter on `/jobs/search`, `/rag/test`, `/web-chat-turn`, `/assist`, `/chatops-actions/*`. Consider fail-closed for the LLM bucket while leaving auth fail-open.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
