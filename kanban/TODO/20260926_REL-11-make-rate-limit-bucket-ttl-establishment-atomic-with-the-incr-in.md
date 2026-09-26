---
id: REL-11
title: "Make rate-limit bucket TTL establishment atomic with the INCR in _enforce_bucket"
severity: low
area: reliability
labels: [redis, availability, auth]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# REL-11 — Make rate-limit bucket TTL establishment atomic with the INCR in _enforce_bucket

**Severity:** low · **Area:** reliability · **Effort:** S · **Labels:** redis, availability, auth

**Trạng thái:** TODO

## Problem

_enforce_bucket does `INCR` and then sets the window TTL only when the returned count is 1. If the process dies or the Redis connection drops between the INCR and the EXPIRE (or the EXPIRE errors), the bucket key persists with no TTL; every later request increments past `limit` and gets 429 permanently, because the TTL is never re-established on subsequent hits.

## Evidence

- backend/app/core/ratelimit.py:44-50 — `count = await redis.incr(key); if count == 1: await redis.expire(key, window); if count > limit: raise HTTPException(429...)` — two round trips, TTL only on first increment
- backend/app/core/ratelimit.py:37-41 — callers include login (Argon2) per-IP and per-email buckets
- backend/app/core/ratelimit.py:56-62 — production-only: the bug cannot manifest in dev/tests (development returns early)

## Impact

Rare but unrecoverable-without-ops availability bug: a production login endpoint returns 429 to that IP/email until someone manually deletes the Redis key — on the auth path whose module docstring says 'auth must stay available'.

## Suggested fix

Use a small Lua script (INCR + EXPIRE when count == 1) or `SET key 1 EX window NX` + INCR so the TTL can never be missing; alternatively refresh `expire(key, window)` on every increment. Add a unit test asserting the key always carries a TTL after the first increment.

## Notes

Fail-open behavior for Redis-down is correct and was reviewed; this is only the non-atomic TTL establishment. `app/core/ratelimit.py` is a protected path — fixing needs owner approval.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
