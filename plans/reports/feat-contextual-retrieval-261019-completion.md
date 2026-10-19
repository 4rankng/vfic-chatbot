# Completion — feat-contextual-retrieval (RAG pack A: Contextual Retrieval)

Copied from `standards/agent-completion-checklist.md` (2026-10-19).

## Task record

- Task: Contextual Retrieval (Anthropic) — chunk context prefix lúc index + env toggle +
  benchmark before/after + backfill path.
- Scope: backend knowledge indexing (LLM-digest path), retrieval benchmark plumbing,
  gold fixtures re-seed, docs/qa evidence. Excludes: canonical `contextual_text`
  (spec-owned), category-revision indexing (separate path, selftest floors calibrated
  unprefixed), mechanical 1-chunk legacy fallback (covered by backfill for existing rows).
- Files changed:
  - `backend/app/core/config.py` — `rag_contextual_enabled` (default true)
  - `backend/app/services/knowledge/contextual.py` — new: deterministic metadata-first prefix
  - `backend/app/services/knowledge/pipeline.py` — `_store_units` renders prefix into embed
    input; `run` computes the digest summary before embedding
  - `backend/app/services/knowledge/chunk_repository.py` — prefix persisted under
    `metadata.contextual_prefix`
  - `backend/scripts/benchmark_rag.py` — `--embeddings PATH` for the gold mode
  - `backend/scripts/seed_rag_gold_contextual_embeddings.py` — new: contextual gold embeddings
  - `backend/scripts/seed_rag_gold_embeddings.py` — baseline.json keeps full precision
  - `backend/scripts/backfill_contextual_prefix.py` — new: re-index existing chunks
  - `backend/tests/fixtures/rag_gold/embeddings.json` — re-seeded at 3072-dim (was a stale
    54-dim artifact); `embeddings_contextual.json` + `baseline.json` added
  - `backend/tests/test_knowledge_contextual.py` — new: 11 unit tests
  - `docs/architecture/database.md`, `qa/contextual-retrieval-benchmark.md` — evidence
- Instructions retrieved: repo `AGENTS.md`; `docs/development/code-standards.md` via
  routing; neighboring `pipeline.py` / `chunk_repository.py` / `benchmark_rag.py`.
- Approval required: none (branch task, no deploy/PR beyond the requested push).
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Prefix at index (toggle, metadata-first), persisted separately; benchmark before/after in `qa/contextual-retrieval-benchmark.md` (pass 92.6%→100%, recall@10 0.9907→1.0, mrr 0.7525→0.8025); backfill script |
| Diff is limited to the approved scope | PASS | `git status --short` — only the files listed above |
| Protected operations were avoided or approved | PASS | No deploy, no branch creation; commit+push were explicitly requested |
| Focused tests/checks pass | PASS | `pytest tests/test_knowledge_contextual.py tests/test_rag_precision_gate.py tests/test_knowledge_pipeline.py -q` → 33 passed |
| Broader regression tests pass when shared behavior changed | PASS | Full `-m "not integration"`: 3968 passed; 15 failures + 3 collection errors reproduced identically on clean HEAD (env-gated Makefile/docker/HTTP-inventory suites) — only new failure was the precision-gate rounding trap, root-caused and fixed in the seeder |
| Lint passes for affected code | PASS | `ruff check .` (backend) → All checks passed! |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` untouched by this diff; changed modules type-check under pytest import + ruff (N/A for pyright scope) |
| Build/import validation passes for affected code | PASS | All new/changed modules imported by the test run; `benchmark_rag.py --gold` executed end-to-end |
| Security and privacy impact reviewed | PASS | Scripts log ids/prefix lengths only, never chunk content; no secrets in code (keys read via Settings env) |
| Performance and async-I/O impact reviewed | PASS | Prefix adds ~1 sentence per embed input; no new LLM call (metadata-first); backfill batches per document with per-document commit |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | N/A — no UI surface |
| Error handling and compatibility reviewed | PASS | Toggle off = legacy behavior (tested); backfill idempotent via metadata marker; canonical units never double-prefixed (tested) |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/architecture/database.md` Embeddings section updated; `qa/contextual-retrieval-benchmark.md` added; agent routing (AGENTS.md) unchanged → doc-links check N/A |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK" backend/app/services/knowledge/contextual.py backend/scripts/backfill_contextual_prefix.py backend/scripts/seed_rag_gold_contextual_embeddings.py` → none |
| Final `git diff --check` passes | PASS | clean (no whitespace errors) |
| Final `git status --short` reviewed | PASS | Only intended files; `baseline.json` intentionally untracked per repo convention |

## Result

- Overall status: DONE
- Remaining risks or follow-ups:
  - `rag_contextual_enabled=false` keeps new ingests unprefixed; a mixed index (old unprefixed
    + new prefixed vectors) is the transient state until `backfill_contextual_prefix.py` runs.
  - Precision-gate baseline (`baseline.json`) stays untracked per existing convention; CI runs
    in shape mode.
  - Pre-existing env-gated suites (deployment Makefile, architecture-boundary TS scan,
    runtime inventory, email-digest integration) fail identically on clean HEAD — untouched.
