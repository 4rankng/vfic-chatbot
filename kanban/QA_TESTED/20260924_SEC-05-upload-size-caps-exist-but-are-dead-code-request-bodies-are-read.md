---
id: SEC-05
title: "Upload size caps exist but are dead code; request bodies are read unbounded"
severity: medium
area: security
labels: [security, reliability]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# SEC-05 — Upload size caps exist but are dead code; request bodies are read unbounded

**Severity:** medium · **Area:** security · **Effort:** S · **Labels:** security, reliability

**Trạng thái:** QA_TESTED

## Problem

The intended 20 MiB upload cap and the zip-bomb guard have no production call site, and every upload and webhook handler reads the entire body into memory before any check.

## Evidence

- `backend/app/services/ingestion/limits.py:13,47-55` — `MAX_UPLOAD_BYTES`, `assert_upload_size`, `assert_archive_metadata`; a repo-wide grep finds only `backend/tests/test_generic_source_blocks.py:9-13,63-66`.
- `backend/app/api/knowledge.py:387-398` and `backend/app/services/knowledge/service.py:355` — `data = await file.read()` then `upload_bytes(...)`; `backend/app/api/personas.py:154-161` reads with no cap at all.
- `backend/app/api/webhooks.py:66-90` — `await request.body()` on all three POST routes (`:101`, `:148`, `:243`).

## Impact

An admin-scoped session POSTs a multi-gigabyte body: the ASGI layer buffers it, `file.read()` materialises a second full copy, and it is written to the uploads volume. The web container has no memory limit (OPS-09) on a 4 GB host.

## Suggested fix

Call `assert_upload_size(len(data))` immediately after every `file.read()` and check `Content-Length` before `request.body()`; return 413. Enforce a hard `max_body_size` at Caddy/uvicorn as the outer bound, since FastAPI has none.

## Evidence log

- c2b46788 — upload cap after every read, Content-Length pre-check and 1 MiB ceiling on webhook bodies (413)
- tests/test_upload_size_guard.py, tests/test_webhook_ingress_limits.py
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
