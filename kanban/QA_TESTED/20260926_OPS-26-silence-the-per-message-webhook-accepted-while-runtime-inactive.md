---
id: OPS-26
title: "Silence the per-message 'webhook accepted while runtime inactive' log until installation activation ships"
severity: low
area: ops
labels: [telemetry, alerting, log-noise]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# OPS-26 — Silence the per-message 'webhook accepted while runtime inactive' log until installation activation ships

**Severity:** low · **Area:** ops · **Effort:** S · **Labels:** telemetry, alerting, log-noise

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The 2026-09-26 incident diagnosis proved this INFO line fires on every single inbound message in prod — `InstallationService.resolve_active()` returns None because the installation tables have never been populated there — so the one log signal that would distinguish a genuine runtime-authority regression from steady state is permanently noisy and unusable for alerting. Meanwhile every turn is enqueued with an empty runtime stamp, so the runtime-authority gate in run_turn has never executed against production traffic and its failure modes are unobservable.

## Evidence

- backend/app/api/webhooks.py:91-100 — `_runtime_authority_or_inactive` logs INFO 'webhook accepted while runtime inactive channel=%s' whenever resolve_active() is None, then returns None so the turn still enqueues
- plans/reports/260926-1325-prod-bot-silence-recovery-completion.md (benign-signal section) — prod installation_state/manifest tables have 0 rows, so the line fires on 100% of traffic and 'must not be treated as a regression'
- backend/app/graph/runner.py:1613-1650 — the stale_runtime_authority/missing_runtime_authority gates only run when a turn carries a runtime stamp, which prod turns never do

## Impact

Alerting on this line would page on 100% of traffic (cry-wolf), and a real regression of the installation/authority rollout is invisible behind the noise; the authority-gate code path accumulates untested-in-prod drift.

## Suggested fix

Demote the line to DEBUG with a once-per-process summary or counter, and add an explicit runbook note that it must never alert; separately schedule the installation-activation rollout so the authority gates start exercising (or delete the dead gate if the rollout is cancelled).

## Notes

Incident-report follow-up; complements the (uncommitted, OPS-25) pipeline-consumer blindness the incident exposed.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
