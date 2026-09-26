---
id: PERF-16
title: "Cache persistence-worker extractor and embedder clients across jobs"
severity: low
area: performance
labels: [workers, http-clients]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# PERF-16 — Cache persistence-worker extractor and embedder clients across jobs

**Severity:** low · **Area:** performance · **Effort:** S · **Labels:** workers, http-clients

**Trạng thái:** TODO

## Problem

worker-persistence builds its extractor and embedder from scratch on every job, and both construct new langchain ChatOpenAI / httpx-backed client instances each time. The chatbot worker deliberately caches these process-wide (client_cache + warm_llm_client_cache) with measured multi-second cold-construction cost; the persistence queue — one job per SENT bot reply — pays a fresh construction plus fresh TLS handshake for every reply, contradicting the same client-reuse directive it sits next to.

## Evidence

- backend/app/workers/persistence_worker.py:84-90 — _build_extractor() → build_minimax_extractor() runs inside _persist_candidate_async, once per job
- backend/app/workers/persistence_worker.py:96-102 — build_embedder(openrouter_api_key=...).batch also constructed per job
- backend/app/graph/factories.py:37-44 — build_minimax_extractor calls _chat_for_role, constructing a new provider client per invocation
- backend/app/graph/clients.py:1174-1188 — _minimax_chat builds a fresh ChatOpenAI per call; langchain_openai creates its own httpx pool per instance
- backend/app/graph/client_cache.py:16-23 and backend/app/workers/chatbot_worker.py:222-260 — the chatbot worker warms _client_cache once per process because client construction measured ~5-7s cold

## Impact

One-plus fresh TLS handshakes and client constructions per sent reply on a queue sharing the same droplet; added per-job latency and socket churn, and a standing exception to the documented client-reuse directive the next worker will copy.

## Suggested fix

Extend graph/client_cache.py with a lazily-built extractor bundle (or expose the cached embedder from _build_cached_clients) and have _persist_candidate_async take clients from the cache instead of calling _build_extractor()/build_embedder() per job; aclose_client_cache already tears the bundle down process-wide at shutdown (async_runner.py shutdown_resources), so lifecycle needs no new handling.

## Notes

The same build-per-job shape exists in make_minimax_llm_json for the ingest worker (factories.py:47-70) and can adopt the same fix in the same change.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
