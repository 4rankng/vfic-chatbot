# Completion — LLM authors every candidate-facing reply

## Task record

- Task: Remove every candidate-facing short-circuit in the turn path so that one
  author (`MiniMaxAgent.agent`) writes the final message; deterministic data is
  handed to it as evidence or as a mandatory instruction, and a turn that cannot
  produce a compliant reply sends nothing.
- Scope: `backend/app/graph/{lanes,clients,grounding,llm,router,proactive,progressive,runner,adapters,direct_context}.py`,
  `backend/app/schemas/bot_run.py`, `backend/app/services/slo_service.py`,
  `backend/scripts/{seed/telemetry,smoke_turn}.py`, two frontend display maps,
  the eight pinned test files plus the new invariant suite, and three routed docs.
  Exclusions: the two operator-approved TingTing verbatim replies
  (`lanes.py` TINGTING_RESET_REDIRECT_REPLY / tingting_hotline_reply), the
  pre-existing unrelated working-tree changes `backend/scripts/benchmark_rag.py`
  and `frontend/.../command-menu-item.tsx` (committed separately), and no schema
  or migration change.
- Instructions retrieved: `AGENTS.md`, `.claude/CLAUDE.md`, the approved plan
  (`local://llm-authored-replies-plan.md`), `docs/ops/deployment-guide.md` §3/§8.
- Approval required: yes — commit, push, and production deploy were requested by
  the operator in this session; `AGENTS.md` requires the completion checklist
  before declaring completion and reading the deployment guide before deploying.
- Approval evidence: operator messages in this session ("Plan approved.",
  "wrap up all changes, commit all code, push, deploy to prod, once everything is
  good, voice-nudge me").

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Invariant grep `grep -rn "return [A-Z_]*_REPLY\|return tingting_hotline_reply\|return OUT_OF_SCOPE" backend/app --include=*.py` → only `lanes.py:390` (TINGTING_RESET_REDIRECT_REPLY) and `lanes.py:411` (tingting_hotline_reply); the third hit `income_contract.py:69` is `_render_safe_reply` returning the authority text as *evidence*, not a candidate-facing return. Six seams covered by `backend/tests/test_llm_authors_every_reply.py` (6 tests) plus the pinned suites. |
| Diff is limited to the approved scope | PASS | `git status --short` reviewed: 26 modified + 1 new test are this task; `backend/scripts/benchmark_rag.py` and `frontend/.../command-menu-item.tsx` are pre-existing operator changes committed separately. No Alembic/`config.py`/port-contract change. |
| Protected operations were avoided or approved | PASS | `git diff --check` clean; no force/push of others' branches (main only); prod deploy only after `release-check`; no destructive SQL or secret touch. |
| Focused tests/checks pass | PASS | `pytest` on the 12 task files incl. `tests/test_llm_authors_every_reply.py` → **334 passed** (pre-commit re-run below). |
| Broader regression tests pass when shared behavior changed | PASS | `make deploy` runs `release-check`: full `pytest -m "not integration" --cov` (backend lane), frontend lane, data lane — recorded below. |
| Lint passes for affected code | PASS | `cd backend && .venv/bin/ruff check .` → "All checks passed!". |
| Type checking passes for affected code | PASS | `cd backend && uvx pyright app/graph` → "0 errors, 0 warnings, 0 informations" (one `direct_context` narrowing fix at `lanes.py:570`). |
| Build/import validation passes for affected code | PASS | Smoke gate `python -m scripts.smoke_turn` → exit 0, probes `single-message`, `progressive-send`, `progressive-send-failure`, `support-oa-hotline`, `support-oa-clarify` all `outcome='sent'/'error'` as designed. Frontend lane runs `npm run build` + `smoke:built`. |
| Security and privacy impact reviewed | PASS | The contact guard still blocks invented phone/e-mail: `ground_reply` now returns `_UngroundedContact` and the agent rewrites once, else the turn suppresses to `""` (no replacement string). No new logging of message content or secrets; `degradation_reason`/`grounding_verdict` trace keys only. `AgentModel.direct` (an extra unguarded model entry point) deleted. |
| Performance and async-I/O impact reviewed | PASS | Income authority turns now spend 1 model round instead of 0 (intentional — the round is tool-free and bounded); all other new rounds run only on degraded paths (exhaustion, contact repair, authority tool unavailable) and are bounded to one (`max_iters` reset to 1). No new blocking I/O; `read.summarize` cascade findings are unrelated pre-existing callsites. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Backend copy change only for operator-approved strings (unchanged); all other replies are model-authored in Vietnamese per the existing instructions. Frontend change is limited to deleting two dead `LANE_LABELS` entries (`fast_lane`, `faq_bypass`) and two dead `SUMMARY_LABELS` keys — no markup, contrast, or focus change. |
| Error handling and compatibility reviewed | PASS | Every removed `return constant` / `return deps.agent.direct(...)` path now either composes one tool-free round or returns `""` (suppression); `runner._authority_gate`/suppression flows unchanged and covered by the outcome-matrix tests. `progressive.py` treats `_UngroundedContact` as "defer to the full reply" (early bubble) and "suppress the remainder". |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 34 paths and 4 make targets across 4 documents all resolve." Routed docs updated where behavior changed: `docs/architecture/system-architecture.md` (retired fast-path/FAQ-bypass diagram + contact-honesty contract) and `docs/decisions/0012-...md` (decision 7). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -- 'backend/**' 'frontend/**' \| grep -E "^\+.*(TODO\|FIXME\|HACK)"` → NONE. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | Reviewed before staging; only task files staged, operator-owned files committed separately. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - `slo_service.py`'s `cached_or_deterministic` SLO now filters `lane = 'agent'`
    (the only emitted lane), so it duplicates `full_answer`. Its registry pair has
    live readers (`DEFAULT_TARGETS`, the `SloResult` row, `test_slo_service`) so it
    was kept rather than deleted; worth an operator decision to fold the two.
  - One extra model round on income-authority turns: watch `llm_calls` / turn
    latency on the dashboard after release; the composition round is tool-free.
  - `proactive.py` direct-context folded into the agent; the proactive nudge still
    parses a JSON decision, so the missing `direct` entry point only changes who
    composes it.
  - Operator note: pi-lens was uninstalled at their request mid-session; its stale
    `ast` finding was reported to `xd://report_issue`.
