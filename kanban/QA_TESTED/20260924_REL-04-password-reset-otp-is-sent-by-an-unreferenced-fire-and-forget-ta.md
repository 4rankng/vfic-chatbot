---
id: REL-04
title: "Password-reset OTP is sent by an unreferenced fire-and-forget task"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# REL-04 — Password-reset OTP is sent by an unreferenced fire-and-forget task

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

**Trạng thái:** QA_TESTED

## Problem

The only code that sends the OTP and writes the email audit rows runs in a task whose handle is discarded, so it can be garbage-collected or lost on reload — silently.

## Evidence

- `backend/app/services/password_reset_service.py:46-50,118` — `asyncio.create_task(self._send_reset_email(...))`, handle dropped.
- `backend/app/services/password_reset_service.py:120-152` — the only sender and the only writer of the `password_reset_email_sent`/`_failed` audit rows.
- Contrast in-repo: `backend/app/workers/chatbot_worker.py:16,38-50` and `backend/app/services/conversation/events.py:99-101` both keep a module-level task set with `add_done_callback`.

## Impact

The API returns 200 ("check your email") while the mail never sends and no failure row is written — the `except` lives inside the task that never ran — while the OTP row is already committed. Silent from the operator's side.

## Suggested fix

Keep a module-level `set[asyncio.Task]` with `add_done_callback`, or use FastAPI `BackgroundTasks`, or move the send onto the existing `persistence_low` queue where a failed job surfaces in `rq:failed`.

## Evidence log

- 4f3e609b — module-level task set with done callback for the OTP send
- tests/test_password_reset_task_retention.py
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
