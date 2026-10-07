# Ops completion record — Messenger ad-prefill unanswered threads (2026-10-07, ~20:43–22:00 +07)

## Outcome

Prod bot is answering candidate messages again. All 20 flagged ad-prefill
threads were unblocked: 15 answered (BOT/SENT), 2 true prefills stopped after
two window-closed refusals per the owner's twice-then-stop policy, 1 organic
thread (`be9abd11…`) is platform-terminal (Meta: "standard messaging window
expired" — needs the candidate to write again; bot/recruiter sends were all
refused there since 18:43, cause of the original refusals unrecoverable
because the containers that held the logs were recreated).

## Root cause

`aa5ba05d` (deployed ~16:12) made the Facebook webhook skip the bot turn for
any message carrying `referral_source=ADS` and stamp
`attribution.ad_prefill_pending`. The marker rides genuinely typed first
messages too, so real questions never reached a single send attempt; the
reconcile sweep also excluded flagged threads, so nothing recovered them.

## Fix shipped (commits 050c5679, d5d4b278, 4e2cf7c9, 593dca88, 7e4c415f)

- Webhook always runs the ADS-marker turn; the send attempt is the test.
- Outcome recorder counts consecutive window-closed refusals
  (`ad_prefill_refusals`), stamps the skip flag on the 2nd; success or the
  candidate's non-referral message resets both keys. Attribution access is
  lazy (`getattr`) so attribution-less test stubs pass through (regression
  caught by the TingTing session's 3 suppression tests, fixed in 7e4c415f).
- Reconcile failed_send machinery (15-min backoff, 2-attempt cap, reset on
  new inbound) supplies the second try — unchanged, already the owner policy.
- `POST /conversations/{id}/force-bot-reply` + console button: recruiter
  lever that clears the flag and answers the pending candidate message.
- Runtime-surface snapshot bumped with attribution (conversations 19→20,
  +1 provider_boundary from 3ab65a44's self-check-in egress, +1
  queue_producer, both digests recomputed; HEAD-worktree scan diff used).

## Prod data changes (backup first)

- `pg_dump --data-only -t conversations` → `/tmp/prefill-conv-full-backup.sql`
  on the host (the targeted `--where` dump failed: PG16 pg_dump has no
  `--where`; the change was made after the full-table dump).
- `UPDATE conversations SET attribution = attribution - 'ad_prefill_pending'
  - 'ad_prefill_refusals' WHERE attribution->>'ad_prefill_pending'='true'`
  → 20 rows; ever-flagged rollback set (45 ids) at
  `/tmp/prefill-rollback-set.txt` (identifiable alternatively by their SYSTEM
  note message).

## Deploy notes

- Root `make deploy` failed twice: (1) parallel push-lane race → run
  `make -C backend push` / `make -C frontend push` solo, then deploy (known
  pattern); (2) the 593dca88 cutover then failed its smoke gate and
  auto-rolled back to blue — a concurrent b09ad653 cutover (operator-run or
  another session; the TingTing session disclaimed it) smoked green minutes
  later, so the gate failure was cold-boot timing, not code. Final live
  state: web/workers/scheduler `7e4c415f`, frontend `d5d4b278`, `/health` OK.

## Open items

- `followup` queue held 162→165 jobs throughout the incident (lead follow-up
  lane, separate feature) — worth a look some time, not part of this.
- `be9abd11`: if the owner wants, a recruiter can contact that candidate via
  another channel; Meta refuses every send on the PSID until they write again.
- Two chat turns timed out at the 60s RQ job timeout in the 12:24–12:36
  window — separate latency issue, not touched here.

## Addendum (22:45–23:00): TingTing OA send failures (-155 / -14014)

Separate incident found the same evening: every send on the TingTing support
OA (`account_key=tingting`) fails with `chunk 1/1 failed: Access token has
expired (-155)` from 21:38, and the lazy refresh is refused with
`-14014 Invalid refresh token`. Timeline: operator pasted fresh credentials
12:11:12 (`updated_by` set — user write); sends OK 12:21–21:06; refresh token
already invalid at 21:38:29; one recruiter send SUCCEEDED at 21:51 amid the
failures. A refused refresh redeems nothing, so the product's lazy refresh
and any later manual attempt (22:41) cannot be the cause of invalidation.

Prime suspect for the invalidation: the refresh token is single-use and the
payroll side demonstrably holds its own live Zalo credential for the same OA
(its ZNS OTP send succeeded at 22:38 while all chatbot sends failed). Two
independent redeemers of one OA's refresh token will keep killing whichever
copy redeems second — the durable fix is single ownership of the OA token
lifecycle. Interim fix: operator re-grant in Settings → Zalo OA.

Second finding in thread `669c0931` (self check-in enable): payroll
`POST /integration/self-checkin/verify` → 200, but
`POST /integration/self-checkin/update` → 400 in 8 ms. OTP flow healthy;
suspect the LGD-only gate / payload mismatch (payroll env
`SELF_CHECKIN_SUPPORTED_PROJECT_CODES`, default "LGD"; open item "confirm
LGD project code in prod DB at e2e" was still pending). Handled by the
TingTing session, which owns the payroll repo.
