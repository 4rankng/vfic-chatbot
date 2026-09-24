---
id: PERF-13
title: "Embedding cache key is un-normalised and each entry is ~60 KB of JSON"
severity: low
area: performance
labels: [performance]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# PERF-13 — Embedding cache key is un-normalised and each entry is ~60 KB of JSON

**Severity:** low · **Area:** performance · **Effort:** S · **Labels:** performance

**Trạng thái:** QA_TESTED

## Problem

The embedding cache hashes the raw query string, so case, Unicode form and trailing whitespace all produce distinct keys, and the value is a JSON array of Python floats. The answer-cache path already normalises its keys.

## Evidence

- `backend/app/graph/tools/_shared.py:22-36` — key = `embed:{provider}:{model}:{dim}:{sha256(query)}` over the raw query; value = `json.dumps(list[float])`; TTL `embedding_cache_ttl_seconds=86400` (`backend/app/core/config.py:196`).
- `backend/app/graph/cache_key.py:47-56` — the answer-cache path already normalises (NFC + lowercase + whitespace collapse).
- `backend/app/core/config.py:196` — `embedding_cache_ttl_seconds: int = 86400`, i.e. one entry per distinct raw string for a day.

## Impact

`"Lương bao nhiêu?"`, `"lương bao nhiêu"` and trailing-whitespace variants are three separate API calls and three ~60 KB Redis values [EST] — which is also what fills the 256 MB budget behind PERF-02.

## Suggested fix

Normalise with the same `normalize_query()` before hashing, and store the vector base64-packed as float16 (~6 KB, so ~10× more entries in the same memory and cheaper to parse). A normalised key cannot change retrieval semantics because the cached vector is reused only for the identical normalised query.

## Notes

Shares its packed-float16 remedy with PERF-02 (audit finding 2, recommendation (iii)); land the two together.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
