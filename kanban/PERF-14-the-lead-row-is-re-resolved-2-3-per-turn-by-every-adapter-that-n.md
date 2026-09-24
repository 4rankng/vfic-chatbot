---
id: PERF-14
title: "The lead row is re-resolved 2–3× per turn by every adapter that needs it"
severity: medium
area: performance
labels: [performance]
effort: S
status: done
found: 2026-09-24
---

# PERF-14 — The lead row is re-resolved 2–3× per turn by every adapter that needs it

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance

## Problem

Each adapter that needs lead context calls `_resolve_lead` itself, so the same lookup repeats two to three times per turn and one redundant `UPDATE` fires when a gender is inferred.

## Evidence

- `backend/app/recruitment/infrastructure/service_adapters.py:15-26` — `_resolve_lead` (`by_zalo_id`, then `by_contact_id` fallback), invoked by `stored_gender` `:109`, `context` `:37` and `record_inferred_gender` `:113-131`.
- `backend/app/graph/runner.py:1338`, `:439` and `:1360` — the three call sites (gender lookup, profile injection, inference write).

## Impact

2–6 duplicate lead queries per turn on the hottest path, plus one redundant `UPDATE` when a gender is inferred. Compounds the write-side race in REL-05.

## Suggested fix

Resolve the lead once in `run_turn`, put it on the turn object, and pass the row (or a small fact-only dict) into both adapters while keeping their fallback logic. Read REL-05 first — it changes the write side of this same path.

## Notes

Split from a merged ticket. The preamble-serialisation half is PERF-06. Related: REL-05.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
