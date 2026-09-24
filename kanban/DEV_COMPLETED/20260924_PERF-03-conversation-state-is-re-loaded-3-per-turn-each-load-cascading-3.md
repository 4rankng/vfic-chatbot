---
id: PERF-03
title: "Conversation state is re-loaded 3× per turn, each load cascading 3–4 SELECTs"
severity: high
area: performance
labels: [performance, reliability]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# PERF-03 — Conversation state is re-loaded 3× per turn, each load cascading 3–4 SELECTs

**Severity:** high · **Area:** performance · **Effort:** M · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

A turn loads the `Conversation` row, then issues two full `db.refresh(conv)` calls whose only consumers are a pure-Python ownership recheck and a conditional SQL UPDATE that is already its own authority. Each load cascades into the `contact` and `channel_identity` `selectin` relationships.

## Evidence

- `backend/app/graph/runner.py:1149` — `svc.get(uuid)` → `backend/app/services/conversation/repository.py:60-61` `db.get(Conversation, id)`.
- `backend/app/graph/runner.py:1213` and `:1036` — `await deps.db.refresh(conv)`, the second inside `_claim_and_dispatch`.
- `backend/app/models/conversation.py:122-125` — `contact` and `channel_identity` are `lazy="selectin"`; `backend/app/models/contact.py:31-33` — `Contact.channel_identities` is also `selectin`.
- `backend/app/services/conversation/bot_path.py:452-471` — `recheck_ownership` is pure Python over the refreshed columns; `:533-557` — `claim_send` is a conditional SQL UPDATE whose `WHERE EXISTS` is the authority, so the refresh adds no correctness.
- `backend/app/workers/reconcile_worker.py:107` — the sweep pays the same cascade per candidate (up to `reconcile_batch_size=50`); `backend/app/recruitment/infrastructure/service_adapters.py:44` reloads the conversation again for the `oa:` lead path.

## Impact

~9–12 SELECTs per turn for ownership bookkeeping alone [EST] — about 25% of turn queries — each also paying the `pool_pre_ping` liveness ping when a new checkout is required. The same cascade is what makes the reconcile sweep and the lead-adapter reload expensive.

## Suggested fix

Replace both `refresh(conv)` calls with a column-scoped refresh — `await deps.db.refresh(conv, ["version", "mode", "status", "bot_lock_owner", "bot_locked_until", "bot_lock_heartbeat_at"])` — or a single scalar `SELECT` used by the recheck and the claim; do not re-fetch the contact selectin (`_contact_display_name` and the outbox channel/recipient reads use the first load). Pass the already-loaded conversation into the lead adapter instead of `get_by_zalo`. The comment at `bot_path.py:452-459` records that a missing refresh previously caused post-takeover sends, so validate against the takeover tests.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
