---
id: TEST-04
title: "The release gate is real but narrow, mislabelled correctness, and not wired to deploy"
severity: high
area: testing
labels: [testing, ops]
effort: M
status: todo
found: 2026-09-24
---

# TEST-04 — The release gate is real but narrow, mislabelled correctness, and not wired to deploy

**Severity:** high · **Area:** testing · **Effort:** M · **Labels:** testing, ops

## Problem

The golden-pass-rate gate is genuinely fail-closed and well unit-tested, but it measures retrieval precision on a committed fixture scored with canned embeddings — no bot turn is executed — while being labelled `correctness`. The latency SLO is disabled in CI so p95 and error-rate cannot block, and no job consumes the gate, so the deploy path can proceed while CI is red.

## Evidence

- `backend/app/services/release_gate.py:21` — `GOLDEN_PASS_RATE_THRESHOLD_PCT = 95.0`, with a fail-closed gate at `:171-176`; the logic is well unit-tested (`backend/tests/test_release_gate.py:70-135`, `test_release_gate_cli.py:50-99`).
- `.github/workflows/quality-gates.yml:233` — `RELEASE_GATE_LATENCY_SLO_ENABLED: "false"`, so `evaluate_release_gate` appends `latency_slo` to `not_evaluated` (`release_gate.py:156-166`) and the p95 and error-rate gates cannot block in CI.
- `.github/workflows/quality-gates.yml:260` — the golden artifact comes from `backend/scripts/benchmark_rag.py --gold --min-pass-rate 0`; in `--gold` mode (`backend/scripts/benchmark_rag.py:180-200`) that is the offline Vietnamese RAG gold set scored with canned embeddings from `tests/fixtures/rag_gold/embeddings.json`, computing precision@3/@5, recall@10 and MRR.
- `release-gate` has no `needs:` and no job consumes it; `Makefile:37/54/60` deploy targets depend on `release-check`, which re-runs the same benchmark locally and never checks CI status.

## Impact

It will block if gold-set retrieval precision drops below 95%, but it is called `correctness` (`GateFailure(gate="correctness", ...)`) while testing retrieval, it never exercises the turn pipeline, and `make deploy` can proceed while CI is red. `--min-pass-rate 0` also means the benchmark script itself can never exit non-zero.

## Suggested fix

Rename the gate to `retrieval_correctness` in `release_gate.py` and its failure detail; add a CI job running `scripts/smoke_turn.py` against a stubbed provider (it already fails closed on `--inject-failure`); make `release-check` require a green CI run for the commit under release (`gh run list --commit "$(git rev-parse HEAD)" --status success`); and either enable the latency SLO in CI with its 30-run window or document explicitly that latency is not release-gated.

## Notes

The turn pipeline itself is genuinely well tested and is **not** a ticket: `backend/tests/test_graph_runner_turn.py` is 2,464 lines / ~60 behaviour tests, ownership and pre-send guards are covered by `test_concurrency.py:594-780`, `integration/test_outbound_finalize_lock_race.py` and `test_llm_semaphore.py:419-462`, and `scripts/smoke_turn.py` with `test_smoke_turn.py` is exactly the right shape for a pre-flip gate. The gap is that no CI gate runs any of it.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
