# ADR-0014: Keep the score-blend reranker disabled — P3-2 measured zero precision lift

- **Status:** Accepted
- **Date:** 2026-10-19
- **Decider:** Operator (via the RAG pack B brief), executed against the P3-2
  decision rule below

## Context

Directive §12/§16 P3 wired an optional post-fusion *score-blend* rerank tail
(`app/services/retrieval/reranker.py`, flag `rag_rerank_enabled`) behind the
promise that it would ship only "after measuring a precision lift on the gold
set". Until now no answer-quality measurement existed — the retrieval
benchmark (`scripts/benchmark_rag.py`) scored context hits only — so the flag
stayed off pending evidence.

Two structural facts shaped the outcome:

1. Production `match_documents` is **vector-only** (the lexical arm was removed
   after a diacritic-fold collision; see `tests/services_runner.py`), and the
   vector arm already returns rows sorted by similarity.
2. `ScoreBlendReranker.rerank` is a **stable sort by that same similarity** —
   on a vector-only, similarity-sorted candidate list it is the identity.

So a zero lift was expected a priori; P3-2's job was to prove it on the real
pipeline, not to assert it.

## Decision

**Keep `rag_rerank_enabled=false` (default unchanged).** Decision rule
(pre-registered in `scripts/eval_answers.py`): enable the flag only when mean
precision@3 lifts by **≥ 2.0 points** on the same golden answer set.

P3-2 evidence — `scripts/eval_answers.py --rerank both`, 39-case golden answer
set (`tests/golden/answers.yaml`), real post-retrieval pipeline over the
rag_gold fixtures, answers generated live by the app's provider
(`deepseek/deepseek-v3.2` via OpenRouter), DeepEval judged through the same
provider, 2026-10-19:

| metric | rerank=off | rerank=on | lift (pts) |
|---|---|---|---|
| mean precision@3 | 0.2991 | 0.2991 | **+0.000** |
| mean precision@5 | 0.1795 | 0.1795 | +0.000 |
| mean recall@10 | 1.0000 | 1.0000 | +0.000 |
| mean MRR | 0.8462 | 0.8462 | +0.000 |
| contextual precision (judge) | 0.8333 | 0.8333 | +0.000 |
| contextual recall (judge) | 0.8462 | 0.8462 | +0.000 |
| fact-hit rate | 0.9697 | 0.9394 | −3.030 |
| faithfulness (judge) | 0.9295 | 0.9365 | +0.702 |
| answer relevancy (judge) | 0.9223 | 0.8979 | −2.437 |

Reading of the table:

- Every **retrieval-side** metric (precision/recall/MRR and both judge-side
  context metrics) is bit-identical across configs — the rerank tail provably
  reorders nothing on the production vector-only path, exactly as the identity
  argument predicted. Precision@3 lift = +0.000 « 2.0 → no decision to make.
- The answer-side deltas (fact-hit, faithfulness, relevancy) are **generation
  and judge sampling noise**: the contexts are identical between configs, so
  the differences cannot be caused by the flag. They are reported as evidence,
  not as decision variables (the rule reads only the deterministic
  precision@3).
- Baseline quality of the shipped pipeline on this set (rerank=off):
  faithfulness 0.93, answer relevancy 0.92, contextual precision 0.83,
  contextual recall 0.85, fact-hit 0.97 — the first baseline for the
  answer-quality release gate thresholds.
- Mean precision@3 (0.30) is dominated by the 6 abstention cases, which
  correctly retrieve zero chunks (floor 0.30 filters every candidate) and score
  0 by convention; non-bait recall@10 is 1.00.

## Consequences

- **Positive:** no behavior change; the flag stays evidence-gated instead of
  shipping a no-op reorder. The eval harness
  (`backend/scripts/eval_answers.py`) now produces the numbers any future
  rerank proposal must beat, in one command.
- **Negative:** the `rag_rerank_*` settings remain inert surface area —
  `rag_rerank_conditional` / `skip_on_single_match` / `skip_on_exact_id` are
  read by no production caller today.
- **Neutral:** re-open this decision when either (a) a lexical arm returns to
  `match_documents` (fusion output is no longer similarity-sorted, so the blend
  can reorder), or (b) a real cross-encoder reranker replaces the score blend —
  the `Reranker` protocol already exists for that swap. Until then the flag
  stays off; `scripts/eval_answers.py --rerank both` re-runs this comparison.

## Related

- `backend/scripts/eval_answers.py` (harness + pre-registered decision rule)
- `backend/tests/golden/answers.yaml` (golden answer set)
- [ADR-0003](0003-postgres-pgvector.md) (retrieval stack)
- `docs/development/testing.md` § "Answer-quality eval (DeepEval)"
