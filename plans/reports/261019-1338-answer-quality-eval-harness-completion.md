# Agent Completion Checklist — RAG pack B: answer-quality eval harness

Copied from `standards/agent-completion-checklist.md` and filled per AGENTS.md
scoped workflow. Date: 2026-10-19.

## Task record

- Task: RAG pack B — answer-quality eval harness (DeepEval) + P3-2 rerank
  decision + report-only release gate
- Scope: (1) DeepEval dependency (`evals` extra, no new runtime/image weight);
  (2) golden answer set (~20-40 Vietnamese questions with expected answer
  points); (3) `backend/scripts/eval_answers.py` scoring generated answers on
  the real post-retrieval pipeline via the app's provider as LLM judge;
  (4) P3-2 rerank A/B (`rag_rerank_enabled` off vs on) with a pre-registered
  ≥2-point precision-lift rule; (5) answer-quality thresholds in
  `scripts/release_gate_check.py`, report-only by default.
- Files changed: `backend/pyproject.toml`, `backend/uv.lock`,
  `backend/tests/golden/answers.yaml` (new), `backend/tests/golden/answers.py`
  (new), `backend/scripts/eval_answers.py` (new),
  `backend/app/core/config.py`, `backend/app/services/release_gate.py`,
  `backend/scripts/release_gate_check.py`,
  `backend/tests/test_answer_gold.py` (new),
  `backend/tests/test_eval_answers.py` (new),
  `backend/tests/test_release_gate_answer_quality.py` (new),
  `backend/tests/test_release_gate.py`, `backend/tests/test_release_gate_cli.py`,
  `docs/development/testing.md`, `docs/architecture/system-architecture.md`,
  `docs/decisions/0014-rerank-flag-stays-disabled.md` (new), this report.
- Instructions retrieved: AGENTS.md routing (`docs/development/code-standards.md`,
  `docs/development/testing.md`, `standards/agent-completion-checklist.md`);
  brief "RAG pack B" (Ragas/DeepEval framework-first, DeepEval primary).
- Approval required: commit + push explicitly requested in the brief; the
  P3-2 rerank decision rule (≥2 points precision lift) was pre-authorized in
  the brief with "if not → record evidence and keep off".
- Approval evidence: brief instructs "Implement + tests + commit + push. NO
  question tools" and names the exact commit subject.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All five brief items shipped: DeepEval in `evals` extra (uv.lock resolved, `uv lock --check` clean); golden answer set `backend/tests/golden/answers.yaml` (39 VN questions, 20-40 range); `scripts/eval_answers.py` runs the real pipeline + DeepEval judge on the app's provider; P3-2 A/B executed (table below + ADR-0014); answer-quality gate in `release_gate_check.py --answer-quality`, default report-only (`RELEASE_GATE_ANSWER_QUALITY_ENABLED=false`). |
| Diff is limited to the approved scope | PASS | `git status --short` lists exactly the files above; no unrelated code touched. The two pre-existing test-contract updates (`test_release_gate.py` not_evaluated set, `test_release_gate_cli.py` Namespace/settings fields) are required by the new gate surface. |
| Protected operations were avoided or approved | PASS | No deploy/merge/branch ops; commit + push only, as instructed. Production config untouched (flag default unchanged: `rag_rerank_enabled=false`, `release_gate_answer_quality_enabled=false`). |
| Focused tests/checks pass | PASS | `pytest -q tests/test_answer_gold.py tests/test_eval_answers.py tests/test_release_gate_answer_quality.py` → 39 passed; `pytest -q tests/test_release_gate.py tests/test_release_gate_cli.py tests/test_golden_dataset.py tests/test_rag_precision_gate.py tests/test_reranker.py tests/test_architecture_boundaries.py` → 76 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration" --ignore=tests/integration` → 3995 passed, 28 skipped, 15 failed at first run; root-caused: 6 × `test_architecture_boundaries` were the fresh worktree missing `frontend/node_modules` (fix: `npm ci` → 21/21 passed); the remaining 9 (7 × `test_deployment_makefile` commands.log harness + 2 × `test_runtime_surface_inventory` snapshot drift) FAIL IDENTICALLY on the untouched main checkout (`/Volumes/LexarSSD/projects/chatbot`, reproduced 2026-10-19) — pre-existing, zero new failures from this diff. The `tests/integration/test_email_digest_cap.py` collection error (no local pgvector service) also reproduces on main. |
| Lint passes for affected code | PASS | `ruff check .` clean over backend (final run below). |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` clean (the repo's type-checked slice; this diff does not change `app/graph`). |
| Build/import validation passes for affected code | PASS | `import scripts.eval_answers` OK; live smoke `--rerank off --judge on --max-cases 2` completed with real judge scores; full run (below) wrote report + gate payload. |
| Security and privacy impact reviewed | PASS | No new credentials: judge + generator reuse the app provider (`app.graph.providers._chat_for_role`), no OpenAI/DeepEval keys. `backend/.env` is gitignored (verified `git check-ignore`); eval reports contain synthetic gold-corpus text only (no user PII); no secrets in logs/output. |
| Performance and async-I/O impact reviewed | PASS | Runtime surface unchanged except the release-gate evaluator (in-memory comparisons in an already-synchronous gate). The eval harness is offline tooling; its LLM calls are bounded by `--concurrency`, run is manual. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes. Vietnamese content is the gold dataset + prompts, reviewed for diacritic-correct matching (`normalize_text`). |
| Error handling and compatibility reviewed | PASS | Judge/generation failures recorded per-case, never abort the run (`run_case`); gate fails closed on malformed/missing payload (`test_cli_blocks_on_malformed_payload`, `test_gate_blocks_when_enabled_and_payload_missing`); `--judge auto` degrades to deterministic-only with a printed note; every-case-error run exits 1. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/development/testing.md` (new "Answer-quality eval" section + table rows), `docs/architecture/system-architecture.md` (benchmarks bullet), `docs/decisions/0014-rerank-flag-stays-disabled.md` (decision + numbers); `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added (`grep -rn "TODO\|FIXME\|HACK"` over new files empty). |
| Final `git diff --check` passes | PASS | `git diff --check` clean (final run below). |
| Final `git status --short` reviewed | PASS | Reviewed before commit; matches the Files-changed list plus untracked report. |

## P3-2 rerank decision (the brief's decision gate)

Run: `MINIMAX_ENABLE=false OPENROUTER_ENABLE=true .venv/bin/python -m
scripts.eval_answers --rerank both --concurrency 8` (39 cases × 2 configs,
live answers + DeepEval judge, 0 errored cases; artifacts `/tmp/p32_eval.json`,
`/tmp/p32_gate.json`). Decision rule pre-registered in the harness: enable
`rag_rerank_enabled` only on ≥ 2.0 points mean precision@3 lift.

| metric | rerank=off | rerank=on | lift (pts) |
|---|---|---|---|
| mean precision@3 | 0.2991 | 0.2991 | +0.000 |
| mean recall@10 | 1.0000 | 1.0000 | +0.000 |
| faithfulness (judge) | 0.9295 | 0.9365 | +0.702 |
| answer relevancy (judge) | 0.9223 | 0.8979 | −2.437 |
| contextual precision (judge) | 0.8333 | 0.8333 | +0.000 |
| contextual recall (judge) | 0.8462 | 0.8462 | +0.000 |

Outcome: **lift +0.000 « 2.0 → `rag_rerank_enabled` stays `false`**, evidence
recorded in ADR-0014. All retrieval-side metrics are bit-identical across
configs (the score-blend tail is an identity on the production vector-only
path); answer-side deltas are generation/judge sampling noise over identical
contexts. Baseline for the (report-only) answer-quality gate recorded:
fact_hit 0.97 / faithfulness 0.93 / relevancy 0.92 / ctx-precision 0.83 /
ctx-recall 0.85.

Gate wiring verified end-to-end:
`scripts/release_gate_check.py --answer-quality /tmp/p32_gate.json` prints
`answer quality (report-only): ...` and passes with the default flags; with
`RELEASE_GATE_ANSWER_QUALITY_ENABLED=true` it prints `(blocking)` and passes on
the recorded baseline.

## Result

- Overall status: PASS
- Remaining risks or follow-ups: (1) 9 pre-existing unit failures on main
  (`test_deployment_makefile` commands.log harness, `test_runtime_surface_inventory`
  snapshot drift) are untouched by this change and should be triaged separately;
  (2) flip `RELEASE_GATE_ANSWER_QUALITY_ENABLED=true` only after a second
  baseline confirms threshold stability (judge noise ≈ ±2-3 pts on this set);
  (3) re-open ADR-0014 if a lexical arm or cross-encoder reranker returns.
