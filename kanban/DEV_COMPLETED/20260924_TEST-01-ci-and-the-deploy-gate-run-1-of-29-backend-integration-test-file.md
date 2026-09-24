---
id: TEST-01
title: "CI and the deploy gate run 1 of 29 backend integration test files"
severity: critical
area: testing
labels: [testing, ops]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# TEST-01 — CI and the deploy gate run 1 of 29 backend integration test files

**Severity:** critical · **Area:** testing · **Effort:** M · **Labels:** testing, ops

**Trạng thái:** IN_PROGRESS

## Problem

The integration lane is 29 files wide, but both CI and the local release gate invoke exactly one of them — the harness smoke test that only proves the lane works. Every concurrency, crash-window, migration-roundtrip and token-binding invariant the team deliberately wrote is therefore unenforced at merge time.

## Evidence

- `.github/workflows/quality-gates.yml:103` — `pytest -m integration tests/integration/test_harness_smoke.py`.
- `Makefile:21` — `release-check` uses the identical single-file invocation, and `Makefile:37/54/60` deploy targets depend on `release-check`.
- `backend/tests/integration/` contains 29 test files; the 28 that never run include `test_outbound_finalize_lock_race.py` (the actual "Đã chặn" production bug — `finalize_outbound_dispatch` clearing a live turn's lock), `test_outbound_crash_window.py`, `test_delivery_receipt_send_unknown.py`, `test_facebook_lifecycle.py`, `test_canonical_channel_identity_migration.py` and `test_project_category_activation.py` (~1,000 lines of category cutover, rollback and snapshot).
- `backend/tests/integration/test_harness_smoke.py:17-63` proves only that the lane works, not that the application does.

## Impact

A PR touching `backend/app/services/outbox_service.py`, `app/services/conversation/bot_path.py` or any migration merges and deploys green with those invariants broken.

## Suggested fix

Change `.github/workflows/quality-gates.yml:103` to `pytest -m integration` (all files) and make the same change in `Makefile:21`. Raise that job's `timeout-minutes` from 20 to 40–45 — each `_alembic()` call spawns a subprocess with `timeout=120` (`backend/tests/integration/conftest.py:64-76`) and the migration tests chain several per test — and add `--durations=25` so the slow lanes stay visible. Keep the smoke file as a fast first step.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
