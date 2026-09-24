# Turn-path performance wave 1 — PERF-03, PERF-06, PERF-14 (2026-09-24)

All three tickets are implemented and green. The turn hot path now does one
lead lookup instead of two to three, reloads only eight ownership columns
instead of the full conversation row twice, and runs the Jev decision call
concurrently with the preamble's database work instead of after it. Full unit
lane: **2275 passed, 42 skipped** (baseline 2243; the delta includes other
teammates' concurrent additions to the shared tree plus 4 new tests here).
Ruff clean across `backend/`.

## PERF-03 — conversation reloads (`runner.py`, `bot_path.py`)

Both full `db.refresh(conv)` calls — the pre-recheck refresh in `run_turn` and
the pre-claim refresh in `_claim_and_dispatch` — are replaced by a
column-scoped refresh over a new `_OWNERSHIP_REFRESH_COLUMNS` list in
`backend/app/graph/runner.py`: `version`, `mode`, `status`, `taken_over_at`,
`updated_at`, `bot_lock_owner`, `bot_locked_until`, `bot_lock_heartbeat_at`.
That list is deliberately wider than the ticket's sketch: the recheck calls
`run_start_guard`, whose SEMI_AUTO branch reads `taken_over_at`/`updated_at`
via `semi_auto_inactive`, so a list without those columns would make the recheck
*less* authoritative than before on semi-auto conversations. With the list in
place the recheck sees exactly what a full refresh would have given it for
every column it reads, and a column-scoped refresh does not trigger the
`contact`/`channel_identity` `selectin` cascade — that is where the 6–8 rescued
SELECTs per turn come from. The claim itself never depended on the refresh for
correctness (its `WHERE EXISTS` is evaluated server-side at commit), and the
post-takeover-sends regression the `bot_path.py` comment warns about is
covered by the existing ownership tests, all passing.

`recheck_ownership`'s docstring in `backend/app/services/conversation/bot_path.py`
now states the narrowed contract explicitly (which columns must be refreshed
and why) so a future cleanup can't drop the refresh or trim the list
unknowingly. The error-path refreshes (OA profile recovery at the old :1250/:1264,
`_authority_gate`'s `refresh_conv=True`) are untouched — they run only on
failures, not per turn.

## PERF-06 — preamble serialisation (`runner.py`)

The Jev `decide_turn` call is now fired as an `asyncio.create_task` in
`run_turn` immediately after `profile_name`/`contact_id` are computed, and
awaited only after the lead lookup and `record_bot_pending` complete. Jev is
HTTP-only on its own httpx client (decisions.py) and touches no DB, so the
shared `AsyncSession` still has exactly one in-flight coroutine at any moment —
the documented not-concurrency-safe constraint is respected. Wall-clock for the
preamble drops from `lead + pending + jev` to `max(lead + pending, jev)`, i.e.
roughly the full 70–500 ms Jev latency is hidden behind database work the turn
was doing anyway. `jev_ms` is stamped inside a small wrapper coroutine so it
still measures the call's own duration, not the overlapped DB time.

Two deliberate scope notes. First, the lead lookup is *not* gathered on an
isolated session: giving it one requires threading `worker_session_factory()`
through `build_deps`/`composition/recruitment.py`, files owned by other
teammates, so the ticket's "only if given an isolated session" condition is
simply not met and the lookup stays sequential — it now overlaps the Jev call
anyway. Second, the project/direct-context step stays exactly where it was
(PERF-04's territory). One behavior nuance worth knowing: if `record_bot_pending`
now raises while the Jev task is mid-flight, the HTTP call finishes into the
void (it writes nothing) instead of never starting; the failure path itself is
unchanged. And because the Jev task is awaited after the pending write, a Jev
port bug that raises despite the internal degrade-everything contract now
surfaces one stage later, after the pending row exists — the abandonment
recorder already resolves that row, which is its designed job.

## PERF-14 — duplicate lead resolution (`runner.py`, `service_adapters.py`)

`run_turn` resolves the lead once per turn through a new public
`ServiceLeadGenderAdapter.resolve_lead` (feature-detected with `getattr`,
matching the `hasattr(deps.zalo, "for_conversation")` / `deps.direct_context`
idioms already in the file), parks it in a local `lead_row`, and hands the same
dict to all three former call sites: `stored_gender`, `record_inferred_gender`,
and — threaded through `_resolve_lane` → `_agent_turn` as an optional kwarg —
`deps.lead.context`. The adapters gained an optional keyword-only `lead=None`
parameter and keep their by-zalo-then-by-contact lookup whenever it is None, so
test doubles and any port without the seam behave exactly as before (the
kwarg is only ever passed when the real seam resolved a row). The two
identical private `_resolve_lead` methods were hoisted into one module-level
helper. Per turn this removes one to two lead lookups; write semantics are
preserved — `record_inferred_gender` still does its read-then-blank-check-then-
`set_gender_by_id` dance, just against the turn's own snapshot instead of a
second read (the concurrent-writer window is REL-05's to fix, untouched here).
No `BotRunState`/`GraphDeps` field was needed — the parameter chain is the
smaller change, and `agent_kwargs` only carries `lead_row` when a row exists,
which is what keeps the narrow `_agent_turn` test doubles valid.

## Evidence

- `backend` `.venv/bin/pytest -m "not integration"` → 2275 passed, 42 skipped.
- Narrow first: `tests/test_graph_runner_turn.py` → 92 passed (4 new:
  column-scoped-refresh contract, resolve-once/reuse, context hand-off, Jev
  overlap); `test_concurrency.py` + `test_smoke_turn.py` + handoff/abandonment/
  outcome-contract/llm_semaphore/proactive → 86 passed; web-chat/runtime-policy/
  universal-platform → 34 passed.
- Integration (local disposable PG): `tests/integration/test_lead_gender_memory.py`
  → 9 passed (2 new: prefetched-row read/write, `context` parity);
  `test_outbound_finalize_lock_race.py` + `test_reconcile_superseded_inbound.py`
  + `test_extraction_intent_escalation_concurrency.py` → 20 passed.
- `.venv/bin/ruff check .` → clean.

## Deferred / out of scope

- **Reconcile sweep cascade** (`workers/reconcile_worker.py:107`): pays the same
  selectin cascade per candidate; explicitly out of scope per the ticket, unchanged.
- **REL-05 gender-write TOCTOU**: the write path is byte-for-byte the old logic
  against the once-resolved row; the race itself is still there for REL-05.
- **Isolated-session lead lookup** (PERF-06's conditional half): blocked on a
  session-factory seam in `factories.py`/`composition/recruitment.py`, owned by
  others; the lookup already hides behind the Jev overlap.
- **`context()`'s OA `get_by_zalo` reload** (PERF-03 evidence item at
  `service_adapters.py:44`): the lead's scope for this wave named only the two
  refreshes; passing the loaded conversation through would need `conv` plumbed
  into `_agent_turn`. Left as a follow-up.
- **PERF-01** (installation authority memo): planned next phase; `runner.py`
  changes here are additive and leave the authority gates untouched.

## Unresolved questions

- Is the plan for PERF-01 to add its memo check inside `run_turn`'s authority
  block (where `runtime_stamp_is_current` runs) or in `build_deps`? Either
  composes with this wave; happy to adjust when that ticket lands.
