---
id: REL-04
title: "Password-reset OTP is sent by an unreferenced fire-and-forget task"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: todo
found: 2026-09-24
---

# REL-04 — Password-reset OTP is sent by an unreferenced fire-and-forget task

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

## Problem

The only code that sends the OTP and writes the email audit rows runs in a task whose handle is discarded, so it can be garbage-collected or lost on reload — silently.

## Evidence

- `backend/app/services/password_reset_service.py:87-88` — `asyncio.create_task(self._send_reset_email(...))`, handle dropped.
- `backend/app/services/password_reset_service.py:90-122` — the only sender and the only writer of the `password_reset_email_sent`/`_failed` audit rows.
- Contrast in-repo: `backend/app/workers/chatbot_worker.py:37-47` and `backend/app/core/events.py:99-101` both keep a module-level task set with `add_done_callback`.

## Impact

The API returns 200 ("check your email") while the mail never sends and no failure row is written — the `except` lives inside the task that never ran — while the OTP row is already committed. Silent from the operator's side.

## Suggested fix

Keep a module-level `set[asyncio.Task]` with `add_done_callback`, or use FastAPI `BackgroundTasks`, or move the send onto the existing `persistence_low` queue where a failed job surfaces in `rq:failed`.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
