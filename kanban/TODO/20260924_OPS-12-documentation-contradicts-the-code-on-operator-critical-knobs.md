---
id: OPS-12
title: "Documentation contradicts the code on operator-critical knobs"
severity: medium
area: ops
labels: [ops, documentation]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# OPS-12 — Documentation contradicts the code on operator-critical knobs

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, documentation

**Trạng thái:** TODO

## Problem

Six documented facts that operators act on are wrong: LLM/embed throttling defaults, the JWT library, the uvicorn worker count, the alembic head, the DB-pool sizing model and whether `make dev` seeds. One runbook also documents a `VARCHAR(32)` revision limit that the code has already widened.

## Evidence

- `docs/deployment-guide.md` ("Scaling knobs") says `LLM_CONCURRENCY_LIMIT` and `EMBED_CONCURRENCY_LIMIT` default to **0 (disabled)**; the code has `llm_concurrency_limit: int = 8` (`backend/app/core/config.py:321`) and `embed_concurrency_limit: int = 6` (`:327`), i.e. the Redis semaphores are **on**.
- `TECH.md:40` says auth is "**python-jose** JWT" and `backend/tests/test_security.py:81` says "jose must reject it"; `backend/app/core/security.py:13-24` documents the deliberate PyJWT migration (python-jose's `ecdsa` / CVE-2024-23342) and imports `jwt` at `:23`.
- `TECH.md:10` claims "Uvicorn `[standard]` … **2 workers** to use both vCPUs" and `prod-env.sh:95` ships `WEB_CONCURRENCY=2`; `backend/Dockerfile:31` pins `"--workers", "1"` and nothing in the image entrypoint reads that variable.
- `TECH.md:24` and `docs/deployment-guide.md:281` say head is `0053_single_page_external_source_sync_state`; the single head is `0054_channel_account_projects` (`backend/alembic/versions/0054_channel_account_projects.py:41`).
- `backend/app/core/config.py:56-58` and `.env.example:17-19` size the DB pool for "2 web + 6 chatbot replicas … ~13 processes" while compose runs one active web plus `replicas: 3` (`backend/docker-compose.yml:85`); `docs/qa-runbook.md:31-32` claims `make dev` seeds the DB, but seeding is the separate `make seed` (`Makefile:67-69`); `docs/deployment-guide.md:296-300` insists revision IDs stay ≤32 chars while `0053_single_page_external_source_sync_state` is 41 and `backend/alembic/versions/0001_baseline.py:39-47` widens the column to 128.

## Impact

Operators tune LLM throttling on a false premise ("semaphores are off" when a turn is capped at 8 concurrent LLM calls and 6 embeds), incident responders follow the docs to a library that is not installed, and capacity math uses a topology that no longer exists.

## Suggested fix

Correct the six claims in `TECH.md`, `docs/deployment-guide.md` and `docs/qa-runbook.md`; better, generate the knob table from `backend/app/core/config.py` defaults with a small script so it cannot drift, and add a CI check asserting `docs/deployment-guide.md`'s HEAD string equals `alembic heads`.

## Notes

Merge with DOC-03 — same drift class, but this ticket is limited to operator-critical knobs. The seeding claim is also part of OPS-18, and the `VARCHAR(32)` claim is part of OPS-20.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
