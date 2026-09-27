---
id: PERF-17
title: "Migration 0055's halfvec match_memories overload is never called — memories retrieval still brute-forces via the vector overload"
severity: medium
area: performance
labels: [database, performance, migration]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# PERF-17 — Migration 0055's halfvec match_memories overload is never called — memories retrieval still brute-forces via the vector overload

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** database, performance, migration

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

0055's stated goal is making the memories HNSW halfvec index usable, but it only CREATE OR REPLACEs the SQL function with a halfvec(3072) first argument. In Postgres, functions are identified by name + argument types, so this adds a second overload; the original vector-typed function stays in every environment. The sole caller passes CAST(:emb AS vector), which resolves exactly to the legacy overload, whose body orders by `embedding <=> query_embedding` on plain vector — unable to use the halfvec HNSW index built by 0016. 0016's own docstring says the index stays unusable until the query casts to halfvec; that follow-up is still incomplete after 0055. The 0055 docstring's reversibility claim ('CREATE OR REPLACE swaps signatures in place') is not Postgres semantics — the downgrade re-creates the vector form but never drops the halfvec overload.

## Evidence

- backend/app/services/retrieval/document_repository.py:167-170 — `SELECT content, similarity FROM match_memories(CAST(:emb AS vector), :k, CAST(:filter AS jsonb))` — the vector argument binds to the vector overload
- backend/alembic/versions/0016_query_perf_indexes.py:6-13 — docstring: pgvector 'will not use the HNSW index until a follow-up adds embedding::halfvec(3072) <=> ...' to the memories query
- backend/alembic/versions/0055_memories_match_halfvec.py:36 — upgrade creates `match_memories(query_embedding halfvec(3072), ...)`; a different-arg-type CREATE OR REPLACE adds an overload, it cannot replace the vector-typed function
- backend/alembic/versions/0055_memories_match_halfvec.py:14-16 and ~:61-75 — the 'reversible, swaps signatures in place' claim vs a downgrade that leaves the halfvec overload behind
- backend/app/graph/memory.py:46-47 — match_memories is the per-turn memory-recall path (search_user_memory tool), so every turn pays the seq-scan cost

## Impact

The memories HNSW index (0016) remains dead weight and memory recall runs exact sequential scans per turn — the deferred-perf state 0016 explicitly documents, unchanged by 0055. Environments also keep a stale extra function after downgrade, contradicting the migration's own reversibility claim.

## Suggested fix

Change document_repository.py:168-169 to cast the query as halfvec — `CAST(:emb AS halfvec(3072))` — mirroring the knowledge_chunks path in the same file, and add an EXPLAIN-based test that memories_embedding_halfvec_hnsw_idx is used. Then `DROP FUNCTION IF EXISTS public.match_memories(vector, integer, jsonb)` in 0055's upgrade (or a 0056) with a matching DROP in the downgrade, and correct the docstring. Postgres resolves exact-type matches over implicit casts, so this cannot regress once the old overload is dropped. Migration edits are approval-gated.

## Notes

Fresh installs have the same shape (0001 baseline vector form + 0016 halfvec index + 0055 halfvec overload), so the caller fix is required everywhere, not just prod.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
