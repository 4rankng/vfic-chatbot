---
id: ARCH-13
title: "`@lru_cache get_settings()` plus seven import-time settings snapshots; `core/db.py` creates the engine at import"
severity: medium
area: architecture
labels: [tech-debt, testing]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-13 — `@lru_cache get_settings()` plus seven import-time settings snapshots; `core/db.py` creates the engine at import

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** tech-debt, testing

**Trạng thái:** IN_PROGRESS

## Problem

Seven modules capture `get_settings()` at import time, which defeats the standard `monkeypatch.setenv` + `cache_clear()` remediation, and `core/db.py` binds the production pool configuration when it is imported.

## Evidence

- `backend/app/core/config.py:469` — `@lru_cache def get_settings()`; snapshots at `backend/app/core/db.py:14`, `core/redis.py:12`, `core/security.py:30`, `realtime/emitter.py:20`, `realtime/socketio.py:34`, `services/conversation/bot_path.py:47` and `main.py:36`.
- `backend/app/services/conversation/bot_path.py:47-48` — `_settings = get_settings()` is frozen at first import, so the lock-TTL and `_SEMI_AUTO_INACTIVITY` decisions cannot be reached by a test that clears the settings cache.
- `backend/app/core/db.py:16,19-26` — the engine is created at import, binding DSN, `pool_size`, `max_overflow`, `pool_timeout` and `pool_recycle`.

## Impact

Importing `app.core.db` anywhere in a test process opens production pool configuration, `models/base.py` import order becomes load-bearing, and `bot_path.py`'s settings are unoverridable — a test-hostility and startup-fragility defect.

## Suggested fix

In `bot_path.py`, replace the module constant with a per-call `get_settings()` read (or accept settings in `__init__`). For `core/db.py`, keep the engine module-level — correct for the app — but move it behind a lazy accessor so tests can import `app.models.base` without opening a pool.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
