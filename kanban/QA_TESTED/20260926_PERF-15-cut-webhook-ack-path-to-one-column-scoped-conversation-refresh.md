---
id: PERF-15
title: "Cut webhook ack path to one column-scoped conversation refresh"
severity: medium
area: performance
labels: [performance, database, hot-path]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# PERF-15 — Cut webhook ack path to one column-scoped conversation refresh

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance, database, hot-path

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

ZaloWebhookService.handle performs three full-session `db.refresh(conv)` calls per inbound message. Conversation.contact and .channel_identity are lazy="selectin", so each refresh re-fetches the row plus both relationship rows — ~9 SELECTs total — when at most one column-scoped refresh after record_inbound is needed to observe a concurrent recruiter takeover. runner.py:85-102 documents this exact cost and already fixed the turn path with _OWNERSHIP_REFRESH_COLUMNS; the webhook path never got the same treatment. The two `svc.get(conv.id)` calls before refreshes are identity-map hits that add nothing.

## Evidence

- backend/app/services/webhook.py:125-126 — `conv = await svc.ensure(...)` immediately followed by full `await db.refresh(conv)`
- backend/app/services/webhook.py:139-140 — second reload: `svc.get(conv.id)` (identity-map hit) + another full `db.refresh(conv)`
- backend/app/services/webhook.py:195-196 — third reload after persist_explicit_name: same pair again
- backend/app/models/conversation.py:122-125 — Conversation.contact and .channel_identity are lazy="selectin", so every full refresh re-fetches both rows
- backend/app/graph/runner.py:85-102 — the repo's own measurement: 'A full db.refresh(conv) also re-fetches the contact and channel_identity selectin relationships — 3–4 extra SELECTs per refresh'; fixed on the turn path with _OWNERSHIP_REFRESH_COLUMNS

## Impact

Every inbound candidate message pays ~9 avoidable SELECTs on the <1s-ack path that also stamps webhook_ack_ms — exactly the cost the repo measured and eliminated on the turn path but not on ingress.

## Suggested fix

Replace the three refreshes with one column-scoped refresh after record_inbound using the runner.py pattern: reload only the columns the guards read (mode, status, version, taken_over_at, assigned_recruiter_id, updated_at, bot_locked_until/bot_lock_owner) — e.g. a shared _GUARD_REFRESH_COLUMNS or a ConversationService.reload_guards(conv) helper — and delete the two redundant svc.get(conv.id) identity hits. Keep the pre-acquire_lock refresh so the takeover race guard stays correct.

## Notes

The same full-refresh pattern is intentional (error-path-only) at runner.py:865,1695,1709 — leave those; only webhook ingress needs the cutover.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
