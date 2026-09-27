# Agent Completion Checklist

## Task record

- Task: fix the TingTing password-reset flow so a repeated `employee/lookup` is no longer refused
  as a rate limit, and the bot stops answering the reset request with the "chưa có thông tin đã
  xác minh"/"xin SĐT" fallback instead of running the guided flow.
- Scope: backend only — the shared external-API admission boundary, the TingTing service state
  split, the `call_tingting_api` tool copy, the runtime prompt rules, the intent criteria/routing
  hint, and the persona line. No frontend, no migration, no dependency, no deploy file.
- Files changed:
  - `backend/app/services/external_api_core.py` — `QuotaDecision(allowed, reason)`; `dedupe` flag.
  - `backend/app/services/tingting_api.py` — `TINGTING_READ_ONLY_PATHS`; read-only lookup skips the
    dedupe bucket (ceiling kept); refusal maps to `duplicate_request` vs `rate_limited`.
  - `backend/app/graph/tools/tingting_api.py` — honest `duplicate_request` copy; the `rate_limited`
    copy no longer claims a one-minute duplicate.
  - `backend/app/graph/context.py` — TingTing carved out of the anti-fabrication fallback; ask only
    the missing identity fields (name, CCCD), never re-ask the phone; no duplicate identical calls.
  - `backend/app/graph/decisions.py`, `router.py`, `persona.md` — `employee_support` covers "đổi
    mật khẩu", not only quên/đặt lại.
  - `backend/tests/test_tingting_api.py` — bucket split, read-only exemption, and the end-to-end
    repeat-lookup regression.
  - `docs/decisions/0012-tingting-password-reset-integration.md`, `docs/system-architecture.md`.
- Instructions retrieved: `AGENTS.md`, `CLAUDE.md`, `docs/deployment-guide.md`,
  `docs/decisions/0012-*`, `standards/agent-completion-checklist.md`.
- Approval required: yes — bot prompts, grounding and routing policy are approval-gated in
  `AGENTS.md`, and the shared admission boundary changes tool behaviour.
- Approval evidence: the user reported the production symptom ("the rate limit is wrong, I just ask
  today first time why rate limit me", "currently I can't ask bot to reset password") and selected
  the recommended option in the `ask` tool: **"Fix 1+2+3 now"** (exempt lookup from dedupe, add the
  honest `duplicate_request` state, fix the prompt fallback).

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Two identical lookups both reach the API; a repeated OTP send is `duplicate_request`; the prompt no longer offers the fallback for TingTing account work and asks only for name/CCCD. `pytest tests/test_tingting_api.py` → 25 passed, including `test_repeated_lookup_succeeds_while_repeated_otp_is_a_duplicate`. |
| Diff is limited to the approved scope | PASS | Only the files listed above; `git diff --stat` for the staged set contains no frontend, migration, dependency, deployment or unrelated file. |
| Protected operations were avoided or approved | PASS | No Alembic version, `.env`, dependency manifest, deployment file or Makefile touched. No commit/push/deploy in this step beyond the user's explicit instruction. |
| Focused tests/checks pass | PASS | `pytest tests/test_tingting_api.py -q` → 25 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest tests/ -q --ignore=tests/integration` → 2437 passed, 24 skipped (baseline 2433 + 4 new). `tests/test_graph_runner_turn.py`, `test_graph_decisions.py`, `test_grounding.py`, `test_integrations_api.py`, `test_runtime_surface_inventory.py` all green. |
| Lint passes for affected code | PASS | `ruff check app/ tests/` → All checks passed. (`ruff format --check` is not a repo gate; it also flags pre-existing, untouched lines.) |
| Type checking passes for affected code | PASS | N/A — backend-only Python change; frontend `tsc` unaffected. |
| Build/import validation passes for affected code | PASS | Full pytest collection imports every changed module (2437 tests collected). |
| Security and privacy impact reviewed | PASS | The dedupe digest still keeps phone/OTP out of Redis; the read-only exemption applies only to the whitelisted lookup path — OTP/verify/reset keep the dedupe and the ceiling; no error body is echoed; no secret enters the prompt. |
| Performance and async-I/O impact reviewed | PASS | One Redis `INCR` pair per non-GET call as before; the lookup now skips one bucket, so the change is neutral-to-lighter. No new I/O. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | N/A — no UI change. User-facing copy is Vietnamese and now distinguishes "không gửi lại" from a genuine "giới hạn tần suất". |
| Error handling and compatibility reviewed | PASS | `QuotaDecision` is the only API change and `consume_write_quota` has a single caller; every outcome remains a state the agent can state truthfully. The autouse test fixture was updated in step. |
| Documentation impact handled | PASS | ADR-0012 decision item 4 and `docs/system-architecture.md` §14b record the read-only exemption and the new state. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK"` over the changed files returned nothing new. |
| Final `git diff --check` passes | PASS | No whitespace errors on the staged set. |
| Final `git status --short` reviewed | PASS | Staged only the task files; the pre-existing unrelated working-tree changes from another session were left untouched (reported to the user). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The system prompt is Redis-cached for 600 s (`preamble_cache._SYSTEM_PROMPT_TTL_SECONDS`), so the
    prompt-rule change takes effect within ≤10 minutes after the deploy — no namespace bump is
    required for a code edit.
  - The `employee_support` routing decision is model-driven (Jev judgments); the criteria and the
    routing hint now name "đổi mật khẩu", but the classification itself is not covered by a unit
    test. Verify with one live Zalo turn after deploy.
  - `worker-chatbot` is the only worker that runs the graph; the fix reaches it on the next deploy.
