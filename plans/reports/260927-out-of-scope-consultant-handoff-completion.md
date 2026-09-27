# Out-of-scope questions off the TingTing OA: phone number, then consultant handoff — completion record

## Task record

- Task: for any message that is **not** from the TingTing support OA, a question outside the
  bot's scope is no longer answered by a generated redirect. The bot asks for the candidate's
  mobile number, and once the number is in hand replies exactly "Vui lòng chờ chuyên viên tư vấn
  liên hệ." and escalates the conversation to a human consultant.
- Scope: backend turn routing + tests + one report. No migration, no frontend change, no
  prompt/persona/tool-definition edit, no TingTing OA behaviour change.
- Files changed:
  - `backend/app/shared/domain/text.py` — added `has_phone()` and the shared `_PHONE_IN_TEXT`.
  - `backend/app/services/lead/probing.py` — dropped its private duplicate `_PHONE_RE`;
    both call sites now use `has_phone` from the shared module.
  - `backend/app/graph/lanes.py` — `OUT_OF_SCOPE_HANDOFF_REPLY` / `_REASON` /
    `OUT_OF_SCOPE_PHONE_ASK`, `_PHONE_ASK_PIVOT_INTENTS`, `_consultant_handoff(reason=…)`
    (was `_tingting_support_handoff`), `_last_bot_message`, `_out_of_scope_ask_key`,
    `_out_of_scope_phone_ask_outstanding`, `_out_of_scope_handoff_turn`; the new branch in
    `_agent_turn`; `out_of_scope` excluded from the clarification and direct-context lanes in
    `_resolve_lane`.
  - `backend/app/graph/runner.py` — import surface and `__all__` follow the rename and export
    the new symbols.
  - `backend/tests/test_graph_runner_turn.py` — 5 new regression tests; the fast-tier metric
    test repointed to the still-reachable below-floor route.
  - `backend/tests/integration/test_support_handoff_reply_send.py` — docstring symbol rename.
  - `plans/reports/260927-out-of-scope-consultant-handoff-completion.md` — this record.
- Instructions retrieved: `AGENTS.md`, `.claude/CLAUDE.md`, `standards/agent-completion-checklist.md`,
  `standards/definition-of-done.md`.
- Approval required: no for the routing change itself. **One prompt change was deliberately NOT
  made** and is listed under follow-ups: widening `_INTENT_CRITERIA` in
  `backend/app/graph/decisions.py` is gated by `AGENTS.md:71` ("changing bot prompts") and was
  left for the operator.
- Approval evidence: operator instruction in-session ("for message not from TingTing OA, if
  customer ask thing not related to the scope you can answer … after getting mobile phone
  number of the user", then "plan, implement, then commit, push").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Off-domain turn off the OA returns `OUT_OF_SCOPE_PHONE_ASK` with no model call and no escalation; the number that follows returns `OUT_OF_SCOPE_HANDOFF_REPLY` + one `out_of_scope_handoff` escalation. 5 new tests in `backend/tests/test_graph_runner_turn.py` cover both turns, the already-known-phone case, the below-floor case, and the mid-flow pivot. |
| Diff is limited to the approved scope | PASS | `git status --short` shows exactly the 7 files above plus `.claude/CLAUDE.md`, which is a pre-existing local Repowise-index change that predates this work and is excluded from the commit. No migration, no frontend file, no protected path. |
| Protected operations were avoided or approved | PASS | No Alembic edit, no webhook/auth/CORS change, no dependency change, no Makefile change. `backend/app/prompts/` untouched. The gated prompt edit (`decisions._INTENT_CRITERIA`) was identified and skipped, not made silently. |
| Focused tests/checks pass | PASS | `.venv/bin/pytest tests/test_graph_runner_turn.py -q -k "off_domain or phone_after or phone_is_known or barely_confident or recruiting_pivot"` → `5 passed, 115 deselected`. |
| Broader regression tests pass when shared behavior changed | PASS (1 pre-existing failure, not from this change) | Full suite `.venv/bin/pytest -q` → `2 failed, 2851 passed, 28 skipped`. Both failures were diagnosed and one fixed. (a) `test_graph_import_guard` failed because the first implementation reached `app.services.lead` from `lanes.py`; the phone predicate was moved to the framework-free `app/shared/domain/text.py`, and that test now passes. (b) `test_runtime_surface_inventory` still reports `provider_boundary` 89 vs the recorded 87 — verified by diffing the scan against a stashed baseline that the ONLY two added sites are `('app/services/tingting_api.py', 'reset', 'delete')` and `('app/services/tingting_api.py', 'count', 'get')`, in a file this change never touches. That count belongs to concurrent uncommitted work in the tree, so the snapshot was deliberately NOT updated. My diff contributes `[]`. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` (whole backend) → `All checks passed!` |
| Type checking passes for affected code | PASS | No mypy/target in this repo's backend gate (`standards/definition-of-done.md` §4 lists backend hints as advisory and puts typecheck under the frontend). New annotations are explicit: `_out_of_scope_handoff_turn(...) -> str \| None`, `_consultant_handoff(..., *, reason: str) -> None`. |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.main; from app.graph.runner import _consultant_handoff, OUT_OF_SCOPE_PHONE_ASK, _out_of_scope_handoff_turn"` → `imports ok`. `has_phone` was placed in `app/shared/domain/text.py` (framework-free) specifically to satisfy `test_graph_import_guard`: graph runtime modules may not import concrete services. |
| Security and privacy impact reviewed | PASS | No new log of message content: the new warning logs only `reason=%s` (a module constant). The handoff escalation writes the same audit shape as the existing TingTing path. Phone numbers are read, never logged. No auth/CORS/rate-limit surface touched. |
| Performance and async-I/O impact reviewed | PASS | No new I/O. The flow adds no model call, no tool call, and no DB read: `lead_row` is the row the runner already resolves once per turn, and the continuation check is a string compare over the already-loaded `recent_messages`. The off-domain turn is now *cheaper* — it no longer spends an LLM generation. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. The only user-visible text is three fixed Vietnamese strings in `backend/app/graph/lanes.py`, matching the operator's wording verbatim for the handoff line. |
| Error handling and compatibility reviewed | PASS | `_consultant_handoff` keeps the existing best-effort `except Exception` → warning shape (log line updated to name the reason). Backward compatible: `_tingting_support_handoff` was private with a single call path, and every caller was migrated — `grep` finds no remaining reference. The fast-tier metric test was repointed (not deleted) to the below-floor route, which is the only fast-eligible path still reaching the agent. |
| Documentation impact handled | PASS | No agent routing, path, or `make` target was added, moved, renamed, or deleted, so `node scripts/check-doc-links.mjs` is not required; it is still run as a cheap confirmation in the Result section. No user-facing setup/architecture/contract change warrants a `docs/` edit — the TingTing OA bullet in `docs/architecture/system-architecture.md` §14b is scoped to that OA and remains true. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added in any touched hunk. |
| Final `git diff --check` passes | PASS | `git diff --check` → exit 0, no output. |
| Final `git status --short` reviewed | PASS | Committed: 6 files (`shared/domain/text.py`, `services/lead/probing.py`, `graph/lanes.py`, `graph/runner.py`, 2 test files) + this report. Deliberately excluded as NOT mine: `.claude/CLAUDE.md` (pre-existing Repowise index) and the concurrent in-flight work in `app/graph/ports.py`, `app/graph/tingting_guide.py`, `app/services/retrieval/repository.py`, `app/services/tingting_api.py`, `app/shared/domain/vietnamese_gender.py`. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  1. **Out-of-scope coverage is only as good as the Jev taxonomy** (NOT changed — gated).
     Application-status and HR-process questions seen in the reported transcript
     ("sao mình trượt", "khi nào trả ứng lương") are not covered by any intent in
     `_INTENT_CRITERIA` (`backend/app/graph/decisions.py:62-75`), so Jev reads them as
     `general`/`faq_detail` and this flow never starts. Widening that dict is a prompt change
     under `AGENTS.md:71` and needs operator approval. **This is the most likely reason a
     user still sees a generated answer to an off-domain question.**
  2. The confidence floor (`ROUTE_CONFIDENCE_FLOOR = 0.5`) deliberately lets a below-floor
     off-domain reading fall through to the model. That is the safe direction — handing a
     working recruiting lead to a human on a shaky reading is the expensive error — but it
     means a genuinely off-domain question Jev is unsure about still gets a generated reply.
  3. The phone ask is re-sent on every off-domain turn while no number is in hand. It is not
     re-sent after a mid-flow pivot back to a recruiting question (`_PHONE_ASK_PIVOT_INTENTS`).
  4. The escalation fires only on the handoff turn. If a candidate never supplies a number the
     conversation is never escalated and the off-domain thread stays bot-owned; the
     `out_of_scope_handoff` reason in the audit trail is the signal to alert on.
