---
id: TEST-20
title: "Hoist the triplicated _reset_local_secret_cache autouse fixture into tests/conftest.py"
severity: low
area: testing
labels: [fixtures, flake-risk, isolation]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-20 — Hoist the triplicated _reset_local_secret_cache autouse fixture into tests/conftest.py

**Severity:** low · **Area:** testing · **Effort:** S · **Labels:** fixtures, flake-risk, isolation

**Trạng thái:** TODO

## Problem

The process-local secret cache in app.core.preamble_cache leaks decrypted values across tests in one process. Three files each define an identical autouse fixture calling preamble_cache._reset_local_secret_cache() around every test; the protection exists only where someone remembered to paste it. Any fourth test file that resolves a secret through the cache without its own copy reintroduces the cross-file pollution class the HEAD commit just fixed for the facebook reveal tests.

## Evidence

- backend/tests/test_facebook_oauth.py:30-42 — autouse _reset_local_secret_cache with docstring explaining a cached value from another test file shadows this module's env-backed stubs
- backend/tests/test_integration_settings.py:76-80 — same fixture, body only, no comment
- backend/tests/test_preamble_cache.py:21-25 — same fixture, third copy
- backend/tests/conftest.py:36-51 — existing autouse pattern (_isolate_redis) showing where a shared reset belongs

## Impact

The next test that reads or reveals a cached secret will copy the same boilerplate or, more likely, forget it and land an order-dependent suite that passes in isolation and fails in the full run.

## Suggested fix

Move one implementation into backend/tests/conftest.py as an autouse fixture (it is cheap: two cache clears) or expose it as a named fixture the three files request; delete the three local copies. Keep it autouse so future secret-touching tests are covered without remembering the incantation.

## Notes

Root-caused by 31d30377 (HEAD, 'isolate the facebook reveal tests…') — the fix stayed file-local instead of moving to conftest.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
