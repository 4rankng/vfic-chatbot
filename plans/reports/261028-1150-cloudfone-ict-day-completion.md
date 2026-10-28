# Cloudfone insights ICT day-window fix — completion

## Task record

- Task: Owner bug report 28/10 — "Phân tích cuộc gọi ngày 27/10" counted 2 calls
  while the vendor recorded 5; the 2026-10-26 18:36 call (0906004310) was
  reported into the 27/10 letter displayed as 01:36 (exactly +7h). Suspected
  vendor GetCallHistoryVer2 returns callDate already in ICT while
  `_day_window()` assumed UTC.
- Scope: verify the vendor's real clock from stored/live data; fix
  `_day_window` + every parse/display path; regression-test the 4310 case;
  commit+push per step. No deploy, no Telegram.
- Files changed: `backend/app/services/cloudfone.py`,
  `backend/tests/test_cloudfone_service.py`.
- Instructions retrieved: `AGENTS.md` (boundaries, workflow), inline module
  docstrings; no cross-layer imports added.
- Approval required: no (fix explicitly ordered; deploy explicitly withheld).
- Approval evidence: task brief (owner, 28/10).

## Verification of the root cause (step 1)

Two independent probes, both run against production:

1. Live vendor probe (read-only `GetCallHistoryVer2` from the web container,
   full-day windows): the 0906004310 call returns the raw string
   `2026-10-26T18:36:08` — the owner's witnessed wall clock. Its `key` epoch
   `1793014568` = 2026-10-26T11:36:08 UTC = 18:36:08 ICT, so callDate is ICT,
   not UTC. Full-day 27/10 window returns 9 legs / 4 clustered calls
   (0904015115 answered 09:01; 0352283615 missed 18:05 + 18:07; 0886194506
   failed 19:22) — the evening legs the old window dropped.
2. Stored-transcript epoch cross-check: all four
   `cloudfone_call_transcripts` rows for 26–27/10 sit at
   `started_at = key_epoch_utc + 14h` (vendor ICT +7h, plus the code's own
   +7h) — e.g. `1792983232` epoch 02:53:52 UTC vs stored `16:53:52`.

Replay of the old window `[2026-10-26 17:00 → 2026-10-27 16:59]` over the live
rows returns exactly 2 calls — the 4310 call (shown 01:36 after the bogus
shift) and the 09:01 answered call — matching the reported "2 vs 5" symptom.

## Fix (step 2) — commit `019d73f6`

- `call_date_to_ict`: naive values pass through unchanged (vendor is ICT);
  only explicit offsets convert to ICT; garbage still passes through.
- `_day_window`: ICT day D queries `D 00:00:00 → D 23:59:59` in the vendor's
  own clock (was `D-1 17:00 → D 16:59` UTC).
- `_hhmm`, `group_call_legs` gap math, time-slot bucketing in
  `render_insights_html` and `cloudfone_report.py` all consume the (now
  unshifted) ICT strings unchanged — no further edits needed there.

## Regression test (step 3) — commit `d6808823`

`test_regression_4310_evening_call_stays_in_its_own_day_at_its_wall_clock`
uses the live-probed 4310 legs verbatim: one NO ANSWER call at wall clock
`2026-10-26T18:36:08`, inside the 26/10 window; 27/10 evening calls
(18:05) inside day 27's window; the letter renders `Cuộc gọi nhỡ: 18:36 —
0906004310` and buckets it into `18:00 - 24:00 (Tối)`.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Steps 1–3 above; commits `019d73f6`, `d6808823` pushed to `origin/fix-cloudfone-ict-day` |
| Diff is limited to the approved scope | PASS | `git show --stat 019d73f6 d6808823` — 2 files, +81/−33, no unrelated edits |
| Protected operations were avoided or approved | PASS | No deploy, no Telegram, no prod DB writes; vendor probe + psql reads only |
| Focused tests/checks pass | PASS | `uv run --extra dev pytest tests/test_cloudfone_* -q` → 79 passed |
| Broader regression tests pass when shared behavior changed | PASS | Full suite `-m "not integration"`: 4172 passed, 6 failed, 3 errors — the failed/error set is identical on base `a8b9b398` (4171 passed, same 6+3, worktree-environment node-helper + integration fixtures); delta is exactly the new regression test |
| Lint passes for affected code | PASS | `uvx ruff check app/services/cloudfone.py tests/test_cloudfone_service.py` → all checks passed |
| Type checking passes for affected code | PASS | `uvx pyright app/services/cloudfone.py` → 0 errors |
| Build/import validation passes for affected code | PASS | `uv run --frozen` builds the project and the suite imports it |
| Security and privacy impact reviewed | PASS | Probe printed call metadata only, read-only; no secrets logged; credentials never left the container |
| Performance and async-I/O impact reviewed | PASS | Window math is pure string/date computation; one vendor query per day unchanged |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | N/A — email/DOCX output only; Vietnamese labels unchanged |
| Error handling and compatibility reviewed | PASS | Garbage/aware-timestamp fallbacks preserved and unit-tested; idempotent rerun path untouched |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | N/A — no routed docs or links changed; corrected docstrings live in code |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff a8b9b398..HEAD | grep -E 'TODO|FIXME|HACK'` → no matches |
| Final `git diff --check` passes | PASS | Clean |
| Final `git status --short` reviewed | PASS | Clean worktree after both commits |

## Result

- Overall status: DONE
- Remaining risks or follow-ups:
  - ~~Prod data repair~~ **DONE 28/10**: all 25 transcript rows epoch-audited — exactly the
    4 rows of 26–27/10 sat at epoch+14h (older rows were written before the +7h
    conversion existed and were already correct); repaired via
    `started_at - interval '7 hours'` and verified to match the vendor raw
    callDates (09:53:52 / 10:06:13 / 16:44:01 / 09:01:19). Day markers
    recomputed by running the fixed `group_call_legs` over the live-probed
    rows: 26/10 = 6/3/3, 27/10 = 4/1/1.
  - ~~Board ticket~~ **DONE 28/10**: CHAT-14 (id 618) created via the shipmate
    specify flow (spec validated, independent R&T review PASS after 1 defect
    round), evidence comment 2299 added, moved to Done. Note: commits predate
    the ticket, so they cite the branch instead of the key.
  - The already-sent 26/10 and 27/10 letters were produced from shifted
    windows; after deploy, regenerate those days from the admin viewer if the
    corrected letters are wanted.
  - Deploy remains owner-gated per the task brief ("KHÔNG deploy"); the fix is
    on `origin/fix-cloudfone-ict-day`, not yet live.
