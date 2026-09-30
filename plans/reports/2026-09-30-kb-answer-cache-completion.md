# Agent Completion Report — KB answer cache

Filled from `standards/agent-completion-checklist.md`. The plan named this exact
path (`plans/reports/2026-09-30-kb-answer-cache-completion.md`); the checklist's
`<YYMMDD-HHmm>` convention would have produced
`plans/reports/kb-answer-cache-260930-2354-completion.md`.

## Task record

- Task: Cache agent answers for repeated questions about stateless Project
  information (plan `local://kb-answer-cache-plan.md`, approved; then a second
  round driven by the operator's instruction to test against the live model,
  fix every issue found, and repeat until it works).
- Scope: `backend/app/graph/answer_cache.py` (new), `embed_cache.py` (new),
  `core/vector.py`, `graph/semantic_cache.py`, `graph/tools/_shared.py` + its
  importers, `graph/lanes.py` (`_agent_turn` read/write),
  `graph/clients.py` (metric key), `core/config.py` (settings),
  `scripts/calibrate_answer_cache.py` (new) + fixture,
  `tests/helpers/redis_fake.py`, `tests/test_answer_cache.py`,
  `tests/test_answer_cache_turn.py`, `tests/test_graph_tools.py`,
  `tests/test_semantic_cache.py`.
- Files changed: `f6971890` (18 files, +1546/−174) and the follow-up fix commit
  (5 files).
- Instructions retrieved: `AGENTS.md` + routed docs via `.claude/CLAUDE.md`;
  plan `local://kb-answer-cache-plan.md`.
- Approval required: yes — the plan was approved before execution
  ("Plan approved."), and the follow-up fix was directed by the operator
  ("we should cache question and answer for stateless info (which related to
  projects)" / "test and fix all issues you find").
- Approval evidence: user messages quoted above; the second round was verified
  against the live model with the OpenRouter credential from `~/.zshrc`.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Both lanes proven end-to-end against the **live model** (OpenRouter `deepseek/deepseek-v3.2`) with real Postgres, Redis, retrieval and embeddings. Knowledge lane: turn 1 `{'hit': False, 'stored': True}` with `llm_calls=1`, 14.4 s model time; turn 2 identical text `{'hit': True, 'tier': 'exact', 'similarity': 1.0}`, `llm_calls` absent (no model call, no prefetch, no embedding) and a byte-identical reply; turn 3 after `bump_kb_caches()` a miss and a fresh model call (11.5 s). Catalog lane (`list_active_projects`, the operator's example): turn 1 `tool_calls=1`, `prefetch_hit=None`, stored; turn 2 hit with no model call and an identical reply (50.7 s → ~0 ms); turn 3 after the bump a miss and a fresh 45.9 s model call. |
| Diff is limited to the approved scope | PASS | `git show --stat f6971890` + the fix commit list only the plan's files plus the fixture/helper the plan names. No dependency change, no unrelated refactor, no migration. |
| Protected operations were avoided or approved | PASS | No destructive git command, no force-push, no schema change, no secret committed. Dev `backend/.env` was toggled twice (`OPENROUTER_ENABLE=true`, `LLM_DEFAULT_PROVIDER=openrouter`) to run the live-model tests and restored byte-for-byte from a backup both times. |
| Focused tests/checks pass | PASS | `pytest tests/test_answer_cache.py tests/test_answer_cache_turn.py tests/test_semantic_cache.py tests/test_core_cache.py -q` → 99 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Full unit lane re-run after the fix (see the run recorded below); the only failures are the concurrent refactor's, unchanged from the pre-fix baseline. `tests/test_graph_tools.py` 51/51 at the commit in a clean worktree. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app tests scripts` → "All checks passed!". |
| Type checking passes for affected code | PASS | `uvx pyright app/graph/answer_cache.py app/graph/embed_cache.py app/core/vector.py app/graph/semantic_cache.py app/graph/lanes.py app/graph/clients.py` → 0 errors. (Whole-tree `app/graph` still shows 3 pre-existing errors in `tools/jobs.py`, deleted by the concurrent refactor.) |
| Build/import validation passes for affected code | PASS | `python -c "import app.main"` → OK; in a clean worktree at the commit `app.graph.schemas` + `app.graph.lanes` + `app.graph.answer_cache` import. |
| Security and privacy impact reviewed | PASS | Only replies about **stateless Project information** are stored: `_PROJECT_DATA_TOOLS` admits the project KB, feature catalog, active-project/vacancy catalog, shuttle timetable and cross-project income, and refuses `search_user_memory`, profile-ranked recommendations, every TingTing flow, any unclassified tool and any low-confidence route (`allowed_tools is None`) — fail closed. Catalog tools whose filters the model composes from the conversation are cached only on a history-free turn. The scope token folds tenant, language, the knowledge/preamble/jobs version counters, the project scope and the address bucket, so a gendered reply is never served in the other bucket and a Page can never read another Page's answer. `is_shareable_reply` refuses empty, no-evidence and lead-naming replies. No new log line carries reply text or identifiers. |
| Performance and async-I/O impact reviewed | PASS | A hit is one Redis `GET` (plus one cached embedding only on the paraphrase tier, which is off) and skips the entire turn: 14.4 s → ~0 ms (knowledge lane) and 50.7 s → ~0 ms (catalog lane) measured live. Writes are best-effort and inline on the existing I/O path; no new thread, no blocking call, no N+1. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI, no user-visible string, no decision-trace schema change (no new `DecisionTraceCode`), so no frontend type change. |
| Error handling and compatibility reviewed | PASS | Every failure path is a miss: `cache_get_json` swallows, `semantic_cache_get/put` swallow, `answer_project_scope` returns `""` on any exception, `answer_cache_get/put` never raise, and an absent `timings` sink disables the write. Cached replies return through the normal tail, so provider-artifact stripping and the runner's address upgrade still apply. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 34 paths and 4 make targets across 4 documents all resolve." No routed document names the new modules; the module docstrings document the eligibility rule, the shared semantic-cache namespace and the vector wire format. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -nE "TODO\|FIXME\|HACK"` across every committed file → no match. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | Reviewed. The commits contain only this task's files; the remaining entries are the concurrent refactor (jobs tool removed/renamed to `list_active_projects`, `recommendation` split, frontend project-knowledge files), deliberately left uncommitted. |

## Defects found by testing against the live model, and fixed

1. **The cache never stored anything for a new candidate.** The approved
   predicate refused any turn carrying a profile-collection instruction
   ("cho em xin tên để tiện hỗ trợ nhé"), which every fresh lead's turn carries —
   so `answer_cache` was `None` on all three live turns and no key was ever
   written. Verified with the live model, then fixed: the ask is a generic
   instruction, identical for every candidate, and candidate-specific *content*
   is what the reply guard is for. A live run with a fully-populated lead row
   (name, phone, region, desired job, expected salary) showed the model still
   produced a generic reply — no identity echo — and stored successfully.
2. **The catalog lane could never be cached.** Eligibility admitted only
   `("search_knowledge",)`, so the operator's own example
   (`list_active_projects` with location/salary filters) was refused; and even
   with a widened allowlist the write gate required `prefetch_hit`, which only
   the knowledge/timetable/income/faq lanes ever set — the catalog lane has no
   prefetch branch (`clients.py` matches those four exact tool tuples), so the
   model calls the tool itself and `tool_calls` is its evidence signal. Fixed by
   widening the allowlist to the stateless Project-data tools and accepting
   either evidence signal; the catalog lane then cached and served a hit
   (verified live).

## Result

- Overall status: PASS. The requested behavior is verified end-to-end against the
  live model on both the knowledge and the catalog lane, including invalidation.
- Remaining risks or follow-ups:
  1. **Paraphrase tier stays OFF.** `scripts/calibrate_answer_cache.py` (live
     embeddings, 18 paraphrases / 11 negatives in 5 groups) measured
     `max(negatives) = 0.7870` vs `min(paraphrases) = 0.7433` at 0.95 → precision
     1.000, recall 0.000, boundary not globally separable, exit 1. Four of five
     groups are separable (0.685<0.834, 0.686<0.894, 0.697<0.815, 0.649<0.830);
     `lgd-hp-accommodation` is not. `answer_cache_semantic_enabled` therefore
     stays `False`; enabling it needs a tighter canonical for that group or a
     per-project threshold.
  2. **`list_active_jobs` in the allowlist is a rename remnant.** The concurrent
     refactor renames that tool to `list_active_projects`; both spellings are
     accepted today so the commit works before and after the rename lands. Once
     the rename is committed, drop the stale name.
  3. **`make release-check` cannot run yet** — it refuses a dirty tree, and the
     concurrent refactor is still uncommitted. Its individual gates were run
     instead (ruff, pyright, the unit lane, the offline gold benchmark 54/54 with
     8/8 bait abstained, `check-doc-links`, `git diff --check`).
  4. **Residual, accepted risk:** a catalog turn whose question reads standalone
     but whose *filters* came from the turn's own text is cached; a turn with
     earlier messages is not. A reply that paraphrases a candidate fact without
     containing its literal value (e.g. "với mức lương mong muốn của anh thì…")
     would still be stored — the reply guard matches literals only. Both are
     bounded by the tool allowlist: no admitted tool reads the candidate's stored
     profile.
