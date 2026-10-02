# Completion — Zalo OA badge no longer returns TingTing support threads

## Task record

- Task: Clicking the Viet Phap (`zalo_oa`) OA icon must not show TingTing chat.
- Scope: backend channel-filter predicates for the conversation inbox (ORM list/count
  + dashboard reason-scoped raw SQL), their tests, and the two routed docs that
  describe the adapter scope. No frontend change (the list is server-filtered).
- Files changed:
  - `backend/app/services/conversation/repository.py` — `_channel_filter_condition`
  - `backend/app/services/dashboard/repository.py` — `_provider_scope` +
    `_attention_reason_source` signature
  - `backend/tests/test_conversation_channel_provider.py`
  - `backend/tests/integration/test_conversation_channel_provider.py`
  - `backend/tests/test_dashboard_attention.py`
  - `docs/architecture/api.md`, `docs/architecture/system-architecture.md`
- Instructions retrieved: `AGENTS.md`, `docs/development/testing.md` (marker),
  `docs/architecture/api.md`, `docs/architecture/system-architecture.md`,
  `standards/agent-completion-checklist.md`.
- Approval required: no.
- Approval evidence: N/A — bug fix, no protected operation.

## Root cause

`tingting_oa` is not a provider; it is the employee-support Zalo OA account
(`account_key = "tingting"`, `provider = "zalo_oa"`). The plain `zalo_oa` badge
filtered on `provider = 'zalo_oa'` alone, so it also returned support threads —
and the reason-scoped page (`attention_reason_page`) compared
`ci.provider = 'tingting_oa'`, matching nothing.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `tests/integration/test_conversation_channel_provider.py::test_plain_oa_badge_excludes_the_support_oa_account` — list, `needs_attention_count`, and reason page each return only the recruitment OA for `zalo_oa` and only the support OA for `tingting_oa` |
| Diff is limited to the approved scope | PASS | `git status --short`: 7 modified tracked files, all in the scope above |
| Protected operations were avoided or approved | PASS | No deploy/commit/push/branch |
| Focused tests/checks pass | PASS | `pytest tests/test_conversation_channel_provider.py tests/test_tingting_support_scope.py tests/test_dashboard_attention.py tests/test_reporting_conversation_attention.py` → 67 passed; `pytest -m integration tests/integration/test_conversation_channel_provider.py` → 3 passed |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration" -p no:randomly -x` → 3532 passed, 28 skipped, 322 deselected |
| Lint passes for affected code | PASS | `ruff check` on the five changed Python files → All checks passed |
| Type checking passes for affected code | N/A | The repo's pyright gate covers only `app/graph` (Makefile); the changed modules are outside it. `ruff` clean. |
| Build/import validation passes for affected code | PASS | `python -c "import app.services.conversation.repository, app.services.dashboard.repository, app.api.conversations"` → IMPORTS_OK |
| Security and privacy impact reviewed | PASS | The account-key literals are code-owned constants (no user input interpolated into SQL); the generic branch still binds `:channel_provider`. No PII logged. |
| Performance and async-I/O impact reviewed | PASS | No extra query or join; one added predicate on the existing identity join. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI/markup change. |
| Error handling and compatibility reviewed | PASS | Generic provider branch unchanged; `zalo_oa` keeps NULL-`account_key` rows in scope (pre-split default), so only the support key is excluded. |
| Documentation impact handled | PASS | `docs/architecture/api.md` (adapter scope now lists all four values + disjointness), `docs/architecture/system-architecture.md` §11.2; `node scripts/check-doc-links.mjs` → Agent routing OK |
| No new unlinked `TODO`/`FIXME`/`HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | `git diff --check` → clean |
| Final `git status --short` reviewed | PASS | Only the 7 scoped files; `backend/repro_*.py` are pre-existing untracked user files, untouched |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: none. Untracked `backend/repro_extract.py` /
  `backend/repro_validate.py` predate this task and were left alone.
