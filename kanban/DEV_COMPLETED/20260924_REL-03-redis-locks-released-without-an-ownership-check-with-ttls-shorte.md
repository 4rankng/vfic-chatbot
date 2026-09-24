---
id: REL-03
title: "Redis locks released without an ownership check, with TTLs shorter than the work they guard"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# REL-03 — Redis locks released without an ownership check, with TTLs shorter than the work they guard

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

**Trạng thái:** DEV_COMPLETED

## Problem

Two locks delete their key blindly in `finally`, and one has a TTL that its own worst-case path exceeds — so a slow holder can delete a successor's lock and admit a third concurrent holder.

## Evidence

- `backend/app/workers/reconcile_worker.py:132-139` — `SET NX EX=300` then a blind `conn.delete(...)`; the sweep can process `reconcile_batch_size = 50` conversations with a session each (`backend/app/core/config.py:415`).
- `backend/app/services/integration_settings.py:812-817` acquires with `nx=True, ex=30` and `:887-897` releases blindly, while the guarded work is two provider POSTs at `zalo_bot_request_timeout = 30` s each plus a DB commit.
- Correct patterns already present: `backend/app/core/singleflight.py:123-138` (GETDEL ownership CAS) and `backend/app/services/profile_enrichment.py:160-172`.

## Impact

For reconcile this is a load/telemetry defect — duplicate replies are still prevented by the atomic `acquire_lock`. For the OA token refresh it is a correctness defect: Zalo refresh tokens are single-use, so two workers redeeming one leaves the loser's stale pair overwriting the winner's and the OA access token invalid until an admin re-authorizes (`backend/app/services/integration_settings.py:866` documents this outcome).

## Suggested fix

Use `singleflight.release(key, leader_id)` (or an equivalent Lua CAS-delete) for both locks, storing a UUID as the value, and size the OA refresh TTL above the sum of the request timeouts it wraps.

## Evidence log

- 2da7723c (OA lock) + fb344ee0 (reconcile tick lock) — UUID owner, TTL above the guarded work, Lua CAS release
- tests/test_zalo_oa_token_refresh.py; tests/test_reconcile_worker.py (_CasRedis)

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
