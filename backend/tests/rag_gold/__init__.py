"""Vietnamese RAG gold-set test package.

Exposes the loader + precision helpers used by the CI gate
(``backend/tests/test_rag_precision_gate.py``) and the local benchmark runner
(``backend/scripts/benchmark_rag.py --gold``).

Scope: this package tests the *post-retrieval pipeline* (reciprocal rank
fusion, MMR dedup, sha256 dedup, rerank) against canned vectors. It does NOT
test true vector recall — embeddings are pre-computed and checked in as
``embeddings.json`` so CI runs offline, fast, and deterministic. See the plan
at ``plans/260718-1946-kb-rag-quality-and-grounding/phase-01-*.md``.
"""
