---
id: REL-9
title: "Pin ChatOps schedule_followup due_at to Asia/Ho_Chi_Minh morning instead of 09:00 UTC"
severity: medium
area: reliability
labels: [timezone, leads, dashboard]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# REL-9 — Pin ChatOps schedule_followup due_at to Asia/Ho_Chi_Minh morning instead of 09:00 UTC

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** timezone, leads, dashboard

**Trạng thái:** TODO

## Problem

ChatopsService.apply_action's schedule_followup branch hardcodes `time(hour=9, tzinfo=timezone.utc)` — 16:00 Vietnam time — for the created FollowUpTask.due_at and lead.next_action_at. The rest of the product treats follow-up scheduling on the Asia/Ho_Chi_Minh calendar: the dashboard's FOLLOWUP_TODAY counter explicitly converts due_at and now() to VN local before comparing dates, with a comment mandating that form.

## Evidence

- backend/app/services/lead/chatops.py:86-89 — `due_at = datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), time(hour=9, tzinfo=timezone.utc))`
- backend/app/services/dashboard/repository.py:249-256 — _vn_today_predicate converts both sides to 'Asia/Ho_Chi_Minh' server-side, comment: 'No naive Python date math'
- backend/app/services/dashboard/repository.py:291-293 — attention_counters uses `vn_today_due = self._vn_today_predicate("f.due_at")` for FOLLOWUP_TODAY
- backend/app/models/provenance.py:381 — WorkingHours.timezone default 'Asia/Ho_Chi_Minh' (deployment-local business time)

## Impact

A recruiter scheduling a next-morning follow-up from ChatOps gets a task that only surfaces in FOLLOWUP_TODAY from 16:00 VN — the task appears in the afternoon/evening and lead.next_action_at displays the same off-hours time. Latent business-logic timezone bug on a real recruiter path.

## Suggested fix

Build due_at from ZoneInfo('Asia/Ho_Chi_Minh') (tomorrow 09:00 ICT = 02:00 UTC), matching the _vn_today_predicate mandate. Add a test asserting a ChatOps-created followup lands in FOLLOWUP_TODAY on its VN due morning.

## Notes

Cross-ref the Phase 1 dashboard spec Timezone section cited at dashboard/repository.py:251.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
