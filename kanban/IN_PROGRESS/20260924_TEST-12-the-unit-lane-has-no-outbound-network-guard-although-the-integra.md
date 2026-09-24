---
id: TEST-12
title: "The unit lane has no outbound-network guard although the integration lane does"
severity: medium
area: testing
labels: [testing]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# TEST-12 — The unit lane has no outbound-network guard although the integration lane does

**Severity:** medium · **Area:** testing · **Effort:** S · **Labels:** testing

**Trạng thái:** TODO

## Problem

The integration conftest blocks all non-loopback HTTP and socket connects, but the unit conftest has no equivalent guard, and it explicitly clears the shared httpx client registry before and after every test. Existing tests stub at the client seam, so nothing fails if a new test forgets to.

## Evidence

- `backend/tests/integration/conftest.py:239-263` — `_block_external_http` monkeypatches `httpx.AsyncClient.request`, `socket.socket.connect` and `socket.connect_ex` to raise on any non-loopback host.
- `backend/tests/conftest.py` (~55 lines) provides only `_isolate_redis` and `_reset_http_singleton_registry` — no network guard.
- `_reset_http_singleton_registry` clears `app.core.http._CLIENTS` before and after every test, which makes construction of a real client more likely in the unit lane.
- Current stubbing is at the client seam only — `backend/tests/test_zalo_oa_service.py` captures URLs, `test_graph_decisions.py` installs a fake httpx client, `test_llm_probe.py` patches `post` — so an unstubbed call has nothing to stop it.

## Impact

An unstubbed call silently makes a live request — cost, latency, nondeterminism, and in CI possibly a hang until the 20-minute job budget fires.

## Suggested fix

Port `_block_external_http` into `backend/tests/conftest.py` as an autouse fixture allowing `127.0.0.1`, `localhost` and `testserver`, so any unstubbed outbound call fails loudly and immediately with the offending host in the message.

## Notes

Do not ticket the auth suite — it is genuinely well tested: `backend/tests/test_security.py` covers argon2 per-call salting and tampered/malformed/expired JWT → `ValueError`, and `test_identity_authentication.py` asserts validation order (non-access token and invalid UUID rejected before any DB lookup) and the exact 401 body.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
