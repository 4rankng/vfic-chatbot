---
id: REL-14
title: "De-duplicate the fallback re-emission in _llm_call_streaming_with_retry before shipping the remainder"
severity: medium
area: reliability
labels: [progressive-send, failover, ux]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-26
---

# REL-14 — De-duplicate the fallback re-emission in _llm_call_streaming_with_retry before shipping the remainder

**Severity:** medium · **Area:** reliability · **Effort:** M · **Labels:** progressive-send, failover, ux

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

On a mid-stream capacity failure, streaming failover re-runs the full completion on the next provider, so `stream.raw` becomes dead-provider-prefix + full-fallback-text. _complete_progressive_prefix knowingly ships `raw[offset:]` as the remainder — the tail of the dead provider's answer followed by the fallback's full answer — after the early bubble already delivered the head. The code only logs a progressive_stream_mismatch warning; nothing de-duplicates the re-emitted prefix and nothing alarms on the flag, so the candidate can read the same opening content twice whenever a provider dies mid-stream under progressive delivery.

## Evidence

- backend/app/graph/provider_failover.py:246-301 — _llm_call_streaming_with_retry marks `emitted_before_failover` ('no later attempt can recall') but _failover_stream re-streams the same `messages` on the next provider, only setting metrics['stream_partial']
- backend/app/graph/runner.py:1382-1393 — `if full_text != raw_stream:` sets `timings['progressive_stream_mismatch'] = True` and logs a warning; the remainder split still uses the contaminated stream.raw
- backend/app/graph/runner.py:1426-1430 — `return ground_reply(remainder_raw, …)` ships the duplicated remainder through the normal claim/dispatch path
- backend/tests/test_llm_failover.py:415-433 — the mid-stream failure test uses a no-op on_delta and pins only the stream_partial flag; no test covers the cumulative delta stream or the runner-level duplicated remainder

## Impact

Duplicated, contradictory text in the candidate's chat on every mid-stream provider switch under progressive delivery (prod-enabled); the mismatch frequency is recorded in stage_timings but is not alarmable, so the defect's real-world rate is invisible.

## Suggested fix

In provider_failover.py, when `emitted_before_failover` is true, suppress on_delta for the fallback's re-emitted prefix (detect overlap against the already-emitted text) or stop streaming and let the caller send only the fallback's full message as the remainder; in runner.py, alarm/dashboard on progressive_stream_mismatch instead of a silent warning.

## Notes

The non-progressive path is unaffected (on_delta is only wired when a stream exists).

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
