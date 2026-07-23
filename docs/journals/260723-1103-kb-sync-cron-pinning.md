# KB sync cron pinning

**Date**: 2026-07-23 11:03
**Severity**: Low
**Component**: `backend/app/core/config.py`, `backend/app/workers/scheduler_utils.py`, `backend/app/main.py`, `backend/app/workers/external_source_sync_worker.py`, `backend/app/workers/single_page_external_source_sync_worker.py`
**Status**: Resolved

## What Happened

A customer (Phương Thúy) asked Frank whether edits to the Google Sheet that feeds
the bot's KB propagate automatically. Frank's answer — "buổi sáng tầm 2 đến 5 giờ
sáng bot sẽ đọc lại trang doc đấy" — described behavior that was, in fact, an
accident. The two KB-from-link sync ticks ran on rq-scheduler's
`interval=86400`, which counts from `datetime.now(timezone.utc)` at every
web-container boot. There was no wall-clock anchor: the "2–5 AM" window was just
whenever the last deploy/restart happened to land, and it drifted by 24h on every
restart. A mid-day deploy would push the next KB re-ingest out by a full day.

## The Brutal Truth

We told a customer the bot syncs in the early-morning window. It didn't, really —
it synced "24h after the last time we happened to restart the web container." The
user-visible symptom was subtle (sync time drifted day to day), so nobody flagged
it until the question was asked directly. The lesson is the usual one: an
interval-based schedule is not a schedule, it's a countdown, and any claim about
"time of day" made on top of it is wishful thinking. We had the right dedupe
machinery already (the `register_unique_tick` work from `f81e6259`); we just
hadn't pointed it at a real clock.

## Technical Details

- Added `Settings.kb_sync_cron: str = "0 20 * * *"` (UTC; = 03:00 ICT, UTC+7,
  no DST) with a `@field_validator` that parses it via `crontab.CronTab` so a
  malformed env value fails fast at startup.
- Added `register_unique_cron_tick(scheduler, func, cron_string)` mirroring the
  existing interval variant's dedupe (cancel prior dupes for this `func_name`,
  then register one job), but calling `scheduler.cron(...)` instead of
  `scheduler.schedule(..., interval=)`.
- Switched both KB ticks in `main.py` lifespan to the cron helper; the other
  four ticks (proactive follow-up, reconcile, outbound dispatch, decision-trace
  retention) stay on the interval variant unchanged.
- Removed the now-dead `DEFAULT_INTERVAL_SECONDS = 86400` constants from both
  worker modules (verified zero importers).
- Key correctness catch from the code review: rq-scheduler 0.14 depends on
  **python-crontab**, NOT croniter (croniter in the lockfile belongs to another
  package). The first validator draft used `croniter`; it would have accepted a
  subtly different language than what the scheduler actually parses. Re-reading
  `uv.lock` and the installed `rq_scheduler/utils.py` caught it before merge.
- Second catch: the "evaluated in UTC" claim is load-bearing on the container
  TZ being unset (the default). Documented inline so a future `TZ=Asia/Ho_Chi_Minh`
  on the container doesn't silently shift the cron by 7h.
- Verification: 19 new/extended tests pass; broader blast-radius
  (lifespan + both worker modules + their API/service tests) = 38 passed, 122
  total with the scheduler suite. `ruff check` clean. Code-reviewer subagent
  verdict: PASS (3 non-blocking MINORs, all addressed).

## What We Tried

- Switched the scheduler registration API from interval to cron rather than
  bolting a "fire at time T" wrapper on top. Smallest change that fixes the
  actual root cause and keeps the proven dedupe machinery intact.
- Made the schedule env-tunable (per project memory: "avoid rule-based /
  hard-code approach") rather than re-hardcoding as a cron constant. Ops can
  shift the time-of-day per environment without a code change.

## What's Next

- On the next deploy, the first KB re-sync lands at 03:00 ICT the following day
  (the cron variant does not fire on boot, unlike the interval variant). Not
  time-critical, but worth telling the customer so they don't expect an
  immediate sync right after the deploy.
- Stronger follow-up (separate approval, deployment-file change): pin
  `ENV TZ=UTC` in `backend/Dockerfile` to make the UTC assumption explicit and
  survive any future container-TZ override.
