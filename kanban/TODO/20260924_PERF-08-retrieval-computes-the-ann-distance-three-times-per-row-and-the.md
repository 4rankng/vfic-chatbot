---
id: PERF-08
title: "Retrieval computes the ANN distance three times per row and the memories halfvec index is unused"
severity: medium
area: performance
labels: [performance]
effort: M
status: todo
column: TODO
opened: 2026-09-24
---

# PERF-08 — Retrieval computes the ANN distance three times per row and the memories halfvec index is unused

**Severity:** medium · **Area:** performance · **Effort:** M · **Labels:** performance

**Trạng thái:** TODO

## Problem

The ANN query computes the same distance expression in its projection, its floor predicate and its ORDER BY, over 200 candidate rows and on the exact `vector` type. The visibility predicate is applied inside the HNSW CTE as a post-filter, and the memories path casts to `vector` so its halfvec index can never be used.

## Evidence

- `backend/app/services/retrieval/repository.py:246-266` — `1 - (c.embedding <=> CAST(:emb AS vector))` is computed three times per row (projection, `WHERE ... >= :floor`, `ORDER BY`), over `rag_ann_candidates=200` rows (`backend/app/core/config.py:192`) → ~600 full 3072-dim distance evaluations per retrieval [EST].
- `backend/app/services/retrieval/repository.py:155-190` — the entire `_chunk_visibility` predicate (`status NOT IN`, `embedding IS NOT NULL`, a per-row `EXISTS` on `knowledge_categories`, a JSONB `@>` filter, two `#>>`/`::date` effective-date extractions) runs inside the HNSW CTE as a post-filter over `LIMIT :candidate_k`; a filtered HNSW scan has no recall guarantee.
- `backend/app/services/retrieval/repository.py:139-165` — `match_memories` (both the fast path and the SQL function at `backend/alembic/versions/0001_baseline.py:558`) casts to `vector`.
- `backend/alembic/versions/0016_query_perf_indexes.py:65-73` — `memories_embedding_halfvec_hnsw_idx`, whose own header says the app "still casts to ``vector``, not ``halfvec`` … the perf win is deferred to that app change".

## Impact

~10–40 ms of avoidable CPU per retrieval [EST], plus a silent recall cliff on scoped or `effective_from`-filtered data because a selective filter can return far fewer than 200 candidates. The memories path is a full scan computing 3072-dim distances whenever the filter is not chat-id-only.

## Suggested fix

Compute the distance once — `SELECT ..., dist AS similarity FROM (SELECT ..., c.embedding <=> CAST(:emb AS halfvec(3072)) AS dist FROM ... WHERE <visibility>) s WHERE dist <= :floor ORDER BY dist` — and use the halfvec cast everywhere so the index expression matches `0016_query_perf_indexes`; cast both `match_memories` variants to `halfvec`; raise `hnsw.ef_search` (session-level `SET LOCAL`) or pre-select candidate ids before the filtered scan if recall on scoped projects matters. The dedupe/rewrite is behaviour-preserving (same rows, same order formula); the ef_search change is a recall/latency trade-off to measure with `scripts/eval_retrieval.py`.

## Notes

Perf finding 16 (dead/unwired subsystems, including the `deadline` parameter `match_documents` never receives — cited at `backend/app/services/retrieval/repository.py:336-338`) is covered by **ARCH-03**; not duplicated here.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
