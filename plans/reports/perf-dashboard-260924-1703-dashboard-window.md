# perf-dashboard — PERF-11, app-code half

**Date:** 2026-09-24 · **Agent:** perf-dashboard · **Status:** DONE (commit `41c9c888`; final full unit lane fully green after the perf-kb repair, see Verification)

## Outcome

The dashboard no longer aggregates the whole `bot_runs` history on every cache miss. `bot_run_summary` is now bounded to a rolling 24-hour window on `started_at`, the five headline counters that used to run as five separate round trips now run as one, and the dashboard cache TTL has a 60-second floor instead of the old 30-second default. Semantics are stated where the numbers are produced and served: repository docstring, service module docstring, and endpoint docstrings in the API layer all say the bot-run aggregates are last-24h figures. No API field was renamed and no migration was added.

## What changed

- `backend/app/services/dashboard/repository.py` — `bot_run_summary` gained `WHERE b.started_at > now() - interval '24 hours'` on both the global and viewer-scoped paths (the scoped path carries the viewer scope in the JOIN condition so the JOIN precedes WHERE; same rows, valid SQL). The predicate rides `bot_runs_started_at_idx` (migration 0033, `(started_at DESC)` — verified present, no migration added). The five `count_*` methods keep their exact original predicates but now live as five scalar subqueries in a single SELECT named `core_counts()` — one round trip, one snapshot, same shape as `attention_counters`. Viewer scope is applied per-subquery: `(TRUE)` fragments for admin, `:uid` param for recruiters. `bot_errors`' all-time predicate is unchanged — the merged counts were not windowed (that would be scope creep). `_scoped_scalar` survives for the two remaining single-value reads (`bot_suppression_rate`, `count_human_conversations`).
- `backend/app/services/dashboard/service.py` — `metrics()` calls `repo.core_counts(recruiter_id)` once instead of five sequential awaits; a module constant `_DASHBOARD_CACHE_TTL_FLOOR_SECONDS = 60` is applied as `max(floor, settings.dashboard_cache_ttl_seconds)` at BOTH cache-write sites (metrics and attention). The setting is still honored upward — the floor only removes the too-low 30 s default, operators can still raise it. Docstrings state the 24h window on bot-run aggregates and that lead/conversation/follow-up counters (incl. `bot_errors`) are current-state.
- `backend/app/api/dashboard.py` — docstrings only. `/dashboard/metrics` now documents the window semantics per field group (24h aggregates; p95 is 7 days; counters current-state). No signature, route, or response-model change.

## Window semantics (the one-paragraph version)

`bot_run_count`, `bot_sent_count`, `bot_suppressed_count`, `bot_success_rate`, and `avg_bot_response_seconds` are now last-24-hours figures. `p95_bot_response_seconds` was already 7-day-windowed and stays that way. `bot_errors`, open conversations, hot leads, pending follow-ups, failed sends, human-mode conversations, and the attention dashboard are current-state, not windowed. The metrics payload is a mix of windows by design; the API docstring spells it out per field group. Frontend: I searched all of `frontend/src` and the `/dashboard/metrics` payload has NO live consumers (the `buildDashboardStats` mapper in `frontend/src/components/atomic-crm/reporting/domain/dashboardMetrics.ts` and the reporting glue expose it, but no component calls them), so there are no on-screen labels to update — I made zero frontend edits per the lead's rule.

## Verification

- Narrow first: `tests/test_dashboard_attention.py` — 39/39 pass (34 existing + 7 new).
- Blast radius: every test file importing the dashboard modules (76 tests across the files that import `services.dashboard` / `api.dashboard` / `schemas.job`): 76/76 pass.
- Full unit lane (`cd backend && .venv/bin/pytest -m "not integration"`), final run after the perf-kb repair of `graph/factories.py`: **2287 passed / 0 failed / 42 skipped** — tree fully green including my commit. (During development, in-flight breakage from other teammates' WIP produced transient failures in their files only — 109 → 42 → 4 as they repaired — and zero failures ever appeared in the dashboard blast radius; I notified the lead about the `factories.py` syntax error mid-flight.)
- New unit tests pin: the 24h predicate (global + scoped), viewer scope + `:uid` param on both changed queries, single round trip for `core_counts` (exactly one `execute` await) with all five original predicates present, service wiring (core_counts/bot_run_summary called once each with the right scope), and the 60 s TTL floor on both cache-write paths (settings ttl=30 → cache write at 60).

## Flagged (not done — approval gates / contract changes)

1. **API field renames** — the ticket says semantics "must be reflected in the API field names/labels". Field names (`bot_run_count` etc.) are an API contract; per the lead I did NOT rename them, only documented the window in docstrings. The Pydantic schema (`app/schemas/job.py`, `DashboardMetrics`) is outside my file ownership, so its field comments/descriptions also still say nothing about windows — an owner of `schemas/job.py` should add the 24h/7d annotations there.
2. **Index for `active_turns`** — `active_turns()` still scans `conversations` on `bot_locked_until > now()` with no supporting index; adding one is migration-gated so it is untouched. Until then that count stays a seq scan.
3. **`bot_runs` retention** — rows are never pruned (the retention worker only nulls `decision_trace`); the 24h window bounds the dashboard's cost but the table still grows forever. A true fix is a retention/purge policy (approval-gated, out of scope).
4. **TTL applies only in production** — the cache (and therefore the TTL floor) engages only when `app_env == "production"`; dev is uncached by design, so the perf win materializes in prod only. Also the floor-vs-setting interaction means a config default of 30 s remains in `core/config.py` (protected file, untouched) — the effective TTL is `max(60, setting)`.

## Unresolved questions

1. `bot_errors` stays all-time (current-state) while `bot_run_summary.errors` (24h) — the dashboard can now show an all-time error total next to a 24h run total. Consistent? Intentional? If ops wants them aligned, that's a one-line predicate addition inside `core_counts` (plus label text), but it changes another metric's semantics and wasn't in scope.
2. Should `bot_suppression_rate` (all-time over SENT+SUPPRESSED) also be windowed for consistency with the 24h success-rate tile? Same reasoning, same one-liner, same scope argument.
3. The frontend mapper (`dashboardMetrics.ts`) and reporting glue are currently dead-ish code for this payload (no component consumes `/dashboard/metrics` today). Is that intentional (metrics UI planned) or leftover? If a consumer comes back, its labels must say "24h" per the new semantics.
4. Who owns `app/schemas/job.py` — the field descriptions there should carry the window annotations so the OpenAPI docs state the semantics, not just the docstrings.
