# Agent Completion Checklist — RAG pack W1 mục 03: Chunk-position audit (Lost-in-the-Middle)

Copied from `standards/agent-completion-checklist.md` and filled per AGENTS.md
scoped workflow. Date: 2026-10-20.

## Task record

- Task: RAG pack W1 mục 03 — Chunk-position audit (Lost-in-the-Middle) + `rag_context_order=position-aware` context assembly + before/after `eval_answers.py` comparison
- Scope:
  1. Audit gold-chunk rank/position distribution across `rag_gold` (54 cases) and `tests/golden/answers.yaml` (39 cases) in final LLM context assembly (`search_knowledge` + `eval_answers.py`), plus audit `answer_cache` / RAG cache stuffing risk.
  2. Implement `order_context_chunks` / `resolve_context_order` in `backend/app/graph/tools/knowledge.py` and `rag_context_order: str = "position-aware"` in `backend/app/core/config.py`.
  3. Wire `--context-order` (`auto` / `similarity` / `position-aware` / `both`) and per-case/aggregate position tracking into `backend/scripts/eval_answers.py`.
  4. Record verbatim before/after `eval_answers.py` results and cache/position audit in `qa/chunk-position-audit.md` + unit tests in `backend/tests/test_context_position_order.py`.
- Files changed:
  - `backend/app/core/config.py`
  - `backend/app/graph/tools/knowledge.py`
  - `backend/app/graph/tools/__init__.py`
  - `backend/scripts/eval_answers.py`
  - `backend/tests/test_context_position_order.py` (new)
  - `qa/chunk-position-audit.md` (new)
  - `plans/reports/261020-chunk-position-audit-completion.md` (new)
- Instructions retrieved: `AGENTS.md`, `standards/agent-completion-checklist.md`, `qa/contextual-retrieval-benchmark.md`, `docs/decisions/0014-rerank-flag-stays-disabled.md`
- Approval required: Commit + push explicitly requested in prompt (`feat(rag): lost-in-middle-aware context assembly + position audit (bảng trước/sau)`).
- Approval evidence: User prompt states `IMPORTANT: do NOT stop after analysis. Implement + tests + commit + push. NO question tools.`

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `rag_context_order` (default `position-aware`) implemented in `backend/app/core/config.py` and `backend/app/graph/tools/knowledge.py`; `scripts/eval_answers.py` updated with `--context-order` and position tracking; live before/after evaluation and `answer_cache` audit recorded verbatim in `qa/chunk-position-audit.md`. |
| Diff is limited to the approved scope | PASS | `git status --short` contains only the 7 scoped files listed above. |
| Protected operations were avoided or approved | PASS | Commit and push on branch `feat-chunk-position` explicitly requested by the user prompt; no deployment or branch deletion performed. |
| Focused tests/checks pass | PASS | `pytest tests/test_context_position_order.py tests/test_eval_answers.py tests/test_graph_tools.py tests/test_retrieval_scope_guards.py tests/test_semantic_cache.py tests/test_architecture_boundaries.py -q` → `152 passed in 5.34s`. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration" --ignore=tests/integration -n auto` + `pytest tests/test_coverage_ratchet.py tests/test_runtime_surface_inventory.py -q` → `4048 passed, 28 skipped, 0 failed`. |
| Lint passes for affected code | PASS | `uvx ruff check .` → `All checks passed!`. |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → `0 errors, 0 warnings, 0 informations`. |
| Build/import validation passes for affected code | PASS | Live `python -m scripts.eval_answers --rerank off --context-order both --judge on --concurrency 8` completed 39/39 cases × 2 modes with 0 errors. |
| Security and privacy impact reviewed | PASS | No secrets logged or committed; cache keys namespace `rag_context_order` to prevent cross-mode cache poisoning; `answer_cache` scope/safety guards untouched. |
| Performance and async-I/O impact reviewed | PASS | `order_context_chunks` is an in-memory `O(N)` list slice over `N <= 20` strings (`< 5 µs`), zero extra I/O or LLM calls. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | Backend RAG context assembly and evaluation harness only; no UI changes. |
| Error handling and compatibility reviewed | PASS | `resolve_context_order` safely falls back to `position-aware` when `Settings` is stubbed with `SimpleNamespace` in unit tests; `_render_capped_evidence` budget capping order preserved before reordering. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `qa/chunk-position-audit.md` written; `node scripts/check-doc-links.mjs` → `Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve.` |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Verified with `rg "TODO|FIXME|HACK"` across changed files (0 matches). |
| Final `git diff --check` passes | PASS | `git diff --check` clean (0 whitespace/conflict issues). |
| Final `git status --short` reviewed | PASS | Reviewed prior to commit; only expected tracked and new files present. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: None. `fact_hit_rate` improved from `0.9545` to `1.0000` (+4.545 pts), `answer_relevancy` improved from `0.7984` to `0.8256` (+2.721 pts), and `edge_rate` improved from `81.82%` to `93.94%` (+12.12 pts) on `embeddings.json` (`96.97%` on `embeddings_contextual.json`).
