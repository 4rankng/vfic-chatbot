# Completion — consultant reply ⇒ SEMI_AUTO; 30-minute bot resume

## Task record

- Task (operator rule, 2026-09-28): after the «Vui lòng chờ chuyên viên tư vấn liên hệ.»
  handoff, a consultant's human reply must demote `HUMAN` → `SEMI_AUTO`, and a `SEMI_AUTO`
  thread returns to bot-answering after 30 minutes of human inactivity (was 5).
- Files changed: `backend/app/services/conversation/bot_path.py` (`_SEMI_AUTO_INACTIVITY`
  5→30 min, docstring), `backend/app/services/conversation/recruiter_receipts.py`
  (both human-message write points demote `HUMAN`→`SEMI_AUTO`, clear `needs_human`),
  `backend/app/services/conversation/reconcile_queries.py` (comment),
  `backend/tests/test_reconcile_worker.py` (inactive case moved to 40 min),
  `backend/tests/test_recruiter_reply_resets_verification.py` (mode-flip assertions),
  `docs/architecture/system-architecture.md`.
- Instructions retrieved: `AGENTS.md`, `docs/architecture/system-architecture.md` §2.3,
  existing `semi_auto()` transition and `run_start_guard` implementations.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | consultant reply on `HUMAN` → `mode=SEMI_AUTO`, `needs_human=False` (`test_record_recruiter_message_resets_the_attempts`); `run_start_guard` admits the bot only after 30 min (`_SEMI_AUTO_INACTIVITY = timedelta(minutes=30)`, reconcile inactive-case test at 40 min enqueues, active-case still skips) |
| Diff is limited to the approved scope | PASS | state module + receipts + one comment + two tests + doc |
| Protected operations were avoided or approved | PASS | no protected paths |
| Focused tests/checks pass | PASS | receipts + reconcile + handoff + composition + dashboard + webhooks: 78 passed |
| Broader regression tests pass | PASS | full non-integration suite green (in-session); integration lane green |
| Lint passes | PASS | ruff clean |
| Type checking | N/A | no repo type checker |
| Build/import validation | PASS | suite imports |
| Security/privacy | PASS | no data-surface change; mode/flags only |
| Performance/async | PASS | attribute writes inside existing commits; zero extra queries |
| Vietnamese UX | PASS | console badge shows SEMI_AUTO (existing rendering); bot resumes automatically after 30 min — no recruiter action needed |
| Error handling/compatibility | PASS | transition only when `mode == HUMAN` — BOT/SEMI_AUTO threads untouched; `taken_over_at` is refreshed by every consultant message so the 30-min window is per-last-reply |
| Documentation impact | PASS | sequence diagram + §2.3 rule paragraph updated; no routed paths moved |
| No new TODO/FIXME/HACK | PASS | none |
| `git diff --check` / `git status` | PASS | recorded before commit |

## Result

- Overall status: PASS
- Remaining risks: conversations escalated to `HUMAN` where the consultant never replies stay
  HUMAN until a manual release — unchanged by design (matches "as soon as human send message"
  trigger semantics).
