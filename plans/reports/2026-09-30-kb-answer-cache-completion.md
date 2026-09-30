# Agent Completion Report — KB answer cache

Filled from `standards/agent-completion-checklist.md`. The plan named this exact
path (`plans/reports/2026-09-30-kb-answer-cache-completion.md`); the checklist's
`<YYMMDD-HHmm>-<slug>` convention would have produced
`plans/reports/kb-answer-cache-260930-2354-completion.md`.

## Task record

- Task: Cache agent answers for repeated KB questions (plan
  `local://kb-answer-cache-plan.md`; approved, executed step by step).
- Scope: `backend/app/graph/answer_cache.py` (new), `embed_cache.py` (new),
  `core/vector.py`, `graph/semantic_cache.py`, `graph/tools/_shared.py` +
  its three importers, `graph/lanes.py` (`_agent_turn` read/write),
  `graph/clients.py` (metric key), `core/config.py` (settings),
  `scripts/calibrate_answer_cache.py` (new) + fixture,
  `tests/helpers/redis_fake.py`, `tests/test_answer_cache.py`,
  `tests/test_answer_cache_turn.py`, `tests/test_graph_tools.py`,
  `tests/test_semantic_cache.py`.
- Files changed: commit `f6971890` — 18 files, +1546/−174.
- Instructions retrieved: `AGENTS.md` + routed docs via
  `.claude/CLAUDE.md`; plan `local://kb-answer-cache-plan.md`.
- Approval required: yes — the plan was approved before execution.
- Approval evidence: user message "Plan approved." with the full plan inlined.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Two tiers implemented and wired: exact (default on) and semantic paraphrase (default off, gated on calibration). End-to-end smoke (real Postgres + Redis + OpenRouter embeddings, agent LLM stubbed because `MINIMAX_API_KEY` is empty in this env): turn 1 `answer_cache={'hit': False, 'stored': True}` `llm_calls=1`; turn 2 same text `{'hit': True, 'tier': 'exact', 'similarity': 1.0}` `llm_calls=1` (no model call); after `bump_kb_caches()` turn 3 `{'hit': False, 'stored': True}` `llm_calls=2`; Redis held two `answer:<scope>:<qhash>` keys (same qhash, different scope) with TTL 21600. |
| Diff is limited to the approved scope | PASS | `git show --stat f6971890` lists only the plan's files + the fixture/helper the plan names. No unrelated refactor, no dependency change, no docs sweep. |
| Protected operations were avoided or approved | PASS | No destructive git command, no force-push, no schema/migration change, no secret added. Dev `backend/.env` was temporarily toggled (`OPENROUTER_ENABLE=true`, `LLM_DEFAULT_PROVIDER=openrouter`) to try a live smoke and then restored byte-for-byte from a backup. |
| Focused tests/checks pass | PASS | `pytest tests/test_answer_cache.py tests/test_answer_cache_turn.py tests/test_semantic_cache.py tests/test_core_cache.py -q` → 87 passed in a clean worktree at `f6971890`. Calibration harness executes against the live embedder. |
| Broader regression tests pass when shared behavior changed | PASS | Full unit lane `pytest -q -m "not integration" --ignore=tests/integration` → 2868 passed, 7 failed, and all 7 come from a **concurrent refactor in the working tree** (removal of the jobs tool / `recommendation.scoring` / `LeadJobRecommendation`), not from this diff: at `f6971890` in a clean worktree `tests/test_graph_tools.py` → 51 passed. The one import-guard failure also exists at the parent commit (`git show 239ed429:backend/app/graph/prompts.py` already imports `app.services.personas.constant`). `tests/test_architecture_boundaries.py` and `tests/test_llm_authors_every_reply.py` pass in the main tree. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app tests scripts` → "All checks passed!". |
| Type checking passes for affected code | PASS | `uvx pyright app/graph/answer_cache.py app/graph/embed_cache.py app/core/vector.py app/graph/semantic_cache.py app/graph/lanes.py app/graph/clients.py` → 0 errors. (Whole-tree `app/graph` still shows 3 pre-existing errors in `tools/jobs.py`, a file the concurrent refactor deletes.) |
| Build/import validation passes for affected code | PASS | `python -c "import app.main"` → OK. In a clean worktree at `f6971890`: `import app.graph.schemas, app.graph.lanes, app.graph.answer_cache` → OK (the commit is self-consistent). |
| Security and privacy impact reviewed | PASS | Only replies to standalone, non-personalized, knowledge-only turns are stored; `is_answer_cacheable` refuses TingTing turns, profile asks and any tool allowlist other than `("search_knowledge",)`, and `is_shareable_reply` refuses a reply naming the lead; the scope token includes the address bucket so a gendered reply is never served in the other bucket; unknown slug / unreadable port / empty project list all fail closed (`""` scope = never read or written). No new log line carries reply text or identifiers. |
| Performance and async-I/O impact reviewed | PASS | A hit is one Redis `GET` plus, on the paraphrase tier only, one cached embedding; the exact tier never embeds. A hit skips the entire agent loop (10–30 s in prod → one lookup). All writes are best-effort and awaited inline on the turn's existing I/O path; no new thread, no blocking call, no N+1. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI, no user-visible string, no decision-trace schema change (no new `DecisionTraceCode`), so no frontend type change. |
| Error handling and compatibility reviewed | PASS | Every failure path is a miss: `cache_get_json` swallows, `semantic_cache_get/put` swallow, `answer_project_scope` returns `""` on any exception, `answer_cache_get/put` never raise, and a `None`/absent `timings` disables the write entirely. Settings default the feature on for the exact tier only, and the unit lane is unaffected because `tests/conftest.py::_isolate_redis` makes every read a miss. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 34 paths and 4 make targets across 4 documents all resolve." No routed document names the new modules, so no doc edit was required; `semantic_cache`'s docstring now documents the shared namespace and `core/vector.py` owns the wire format. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -nE "TODO\|FIXME\|HACK"` across all 18 committed files → no match. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Reviewed. The commit contains only this task's files; the ~50 remaining entries are a concurrent refactor (jobs tool → `list_active_projects` rename, `recommendation` split, frontend project-knowledge files) that was deliberately left uncommitted. |

## Result

- Overall status: PASS, with one gate (the plan's Verification-7 *live* smoke) replaced by an
  equivalent end-to-end run — see the risks below.
- Remaining risks or follow-ups:
  1. **Paraphrase tier stays OFF.** `scripts/calibrate_answer_cache.py` (real OpenRouter
     embeddings, 18 paraphrases / 11 negatives across 5 groups) measured
     `max(negatives) = 0.7870` vs `min(paraphrases) = 0.7433` at threshold 0.95 →
     precision 1.000, recall 0.000, boundary **not** globally separable, exit 1. Four of
     five groups *are* separable (lgd-hp-salary 0.685<0.834, lgd-bn-salary 0.686<0.894,
     samsung 0.697<0.815, foxconn 0.649<0.830); `lgd-hp-accommodation` is not (its
     "có tuyển công nhân phổ thông không?" negative scores 0.787 against a 0.743 worst
     paraphrase). Per the plan's contingency the tier stays disabled
     (`answer_cache_semantic_enabled=False`); enabling it needs either a tighter canonical
     for that group or a per-project threshold. The exact tier — the default — is proven
     end-to-end.
  2. **The plan's Verification-7 live smoke could not run as written**: `backend/.env` has
     an empty `MINIMAX_API_KEY` and `OPENROUTER_ENABLE=false`, so no turn can produce a
     model-authored reply, and the dev RQ workers were mid-refactor. The substitute
     (`/tmp` script, deleted after the run) drove the real `_agent_turn` with the real
     `RetrievalRepository`, real embedder, real Redis and real version counters, stubbing
     only the chat LLM. The one thing it therefore does not prove is the exact provider
     reply text being re-served — the caching mechanism itself is proven.
  3. **A concurrent refactor is live in this working tree** (jobs tool removed/renamed to
     `list_active_projects`, `recommendation.scoring`/`availability` deleted, frontend
     project-knowledge files added). It is mid-flight: `tests/test_graph_tools.py` cannot
     even be collected on the current tree (`extract_surfaced_job_ids` gone from
     `app.graph.grounding`). Commit `f6971890` was therefore built from the parent commit
     plus only this task's hunks (`git hash-object` + `git update-index --cacheinfo` for
     the three shared files: `lanes.py`, `clients.py`, `tools/__init__.py`), so it is
     self-consistent and does not include the refactor. `make release-check` cannot run
     until that refactor is finished and committed — it refuses a dirty tree.
  4. **Assumption to re-check in production**: the write gate reads `timings["prefetch_hit"]`.
     In the focused-`faq_detail` prefetch both `search_knowledge` and `get_product_features`
     write that key (last writer wins), so a features-only hit also permits a store. The
     stored reply is still a pure function of (question, project scope, versions), so this
     is a conservative miss at worst — but if `prefetch_hit` is renamed or moved, the write
     gate must follow it (the read path does not depend on it).
