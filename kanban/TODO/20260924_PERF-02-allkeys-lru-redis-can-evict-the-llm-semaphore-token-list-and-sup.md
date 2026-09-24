---
id: PERF-02
title: "`allkeys-lru` Redis can evict the LLM semaphore token list and suppress every turn"
severity: high
area: performance
labels: [performance, reliability]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# PERF-02 — `allkeys-lru` Redis can evict the LLM semaphore token list and suppress every turn

**Severity:** high · **Area:** performance · **Effort:** S · **Labels:** performance, reliability

**Trạng thái:** TODO

## Problem

Redis runs `--maxmemory-policy allkeys-lru`, so every key is an eviction candidate, including `llm_sem_tokens`. The semaphore registers its tokens once per process and never re-checks, and the largest key population is the embedding cache, which stores ~60 KB JSON float arrays.

## Evidence

- `backend/docker-compose.yml` (redis service) — `--maxmemory 256mb --maxmemory-policy allkeys-lru`, so `llm_sem_tokens` and `cachever:*` are evictable.
- `backend/app/graph/llm_semaphore.py:60-75` — `_ensure_tokens()` returns immediately once `self._initialized` is true (set on the first acquire in the process); nothing re-registers tokens after startup.
- `backend/app/graph/tools/_shared.py:22-36` with `backend/app/core/config.py:196` — one JSON embedding per unique query, TTL 86400; a 3072-dim float vector as JSON ≈ 60 KB, so ~4 300 entries fill 256 MB, and entries are LRU-refreshed on read [EST].
- `backend/app/core/cache.py:38-46` — `cache_version()` returns `"1"` when the key is missing, so an evicted `cachever:knowledge` counter resets the namespace instead of invalidating it (RAG 300 s, semantic 1800 s, system prompt 600 s, installation fingerprint 600 s).
- `backend/app/workers/chatbot_worker.py:503` — a turn that raises `LLMThrottled` is recorded SUPPRESSED.

## Impact

Outage: if `llm_sem_tokens` is evicted, `BLPOP` returns `None` after `llm_acquire_timeout_seconds=1.5`, `__aenter__` raises `LLMThrottled`, and nothing is sent to any candidate until every web and worker process restarts — no process self-heals because `_ensure_tokens` is once-per-process. Token leak: `SimpleWorker` runs jobs in-process, so an OOM-killed job never reaches `__aexit__`; 8 such deaths with `llm_concurrency_limit=8` is a permanent deployment-wide throttle. Stale data: counter eviction makes old `v{n}` entries live again rather than flushing them.

## Suggested fix

Switch to `--maxmemory-policy volatile-lru` and give `llm_sem_tokens`, `llm_embed_sem_tokens` and `cachever:*` no TTL — that alone removes the outage class; make `_ensure_tokens()` run on every acquire when `llen < limit` (a cheap `LLEN`, or a Lua script that acquires or refills); shrink the embedding payload ~10× by storing packed float16/base64 instead of JSON floats; write `cachever:*` with a long TTL and treat a miss as a full flush rather than a reset to `"1"`.

## Notes

Perf finding 8 (blocking synchronous Redis on the event loop, including this semaphore's release in `llm_semaphore.py:171-190`) is covered by **REL-02**; not duplicated here.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
