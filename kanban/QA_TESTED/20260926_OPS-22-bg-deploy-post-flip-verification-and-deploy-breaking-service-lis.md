---
id: OPS-22
title: "bg_deploy post-flip verification and deploy-breaking service lists omit worker-maintenance and metrics-watch"
severity: high
area: ops
labels: [ops, deploy, reliability]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# OPS-22 — bg_deploy post-flip verification and deploy-breaking service lists omit worker-maintenance and metrics-watch

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, deploy, reliability

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

bg_deploy.sh grew WORKERS to include worker-maintenance and metrics-watch (the 2026-09-26 drift fix), but the dependent service lists were not updated. verify_post_flip_readiness still polls only six services, so worker-maintenance (which actually pushes bot replies to Zalo) and metrics-watch can sit unhealthy or crash-looping after the flip while the deploy declares success — recreating the exact drift class the fix was for, now with no health assertion. Separately, backend/Makefile deploy-breaking pulls and force-recreates a hardcoded seven-service list that omits both, so a breaking-migration deploy leaves old-code workers running against an incompatible schema.

## Evidence

- backend/scripts/bg_deploy.sh:36 — WORKERS="worker-chatbot worker-persistence worker-ingest worker-followup scheduler worker-maintenance metrics-watch" (both added 2026-09-26)
- backend/scripts/bg_deploy.sh:245-250 — verify_post_flip_readiness polls require_running_service_count for frontend, worker-chatbot, worker-persistence, worker-ingest, worker-followup, scheduler only
- backend/scripts/bg_deploy.sh:340-352 — step 4 force-recreates web-$NEXT plus all NON_TURN_WORKERS from $WORKERS, so both omitted services are already replaced before the flip
- backend/scripts/bg_deploy.sh:35-36 — inline comment names worker-maintenance 'the component that actually pushes bot replies to Zalo' and metrics-watch as the queue-depth alert poller
- backend/Makefile:161,167 — deploy-breaking pull/up lists: `web-blue worker-chatbot worker-persistence worker-ingest worker-followup scheduler frontend` — no worker-maintenance, no metrics-watch

## Impact

A deploy can flip traffic and report success while the outbound dispatcher is unhealthy or missing — candidates' replies silently stop sending, with deploy gates green and (metrics-watch down) no in-stack alert firing. On the deploy-breaking path the outcome is worse by design: stale-code workers run against a schema the migration just made incompatible with them.

## Suggested fix

Extend the bg_deploy.sh:245-250 poll loop with require_running_service_count for worker-maintenance and metrics-watch (bg_rollback.sh's copy of the list too). Add the two services to backend/Makefile:161 and :167. Pin the invariant with a repo-level regression test asserting every ${IMAGE_TAG} service from docker-compose.yml appears in both lists.

## Notes

The known hold covered only the creation gap inside bg_deploy.sh (fixed in WORKERS). These are the lists that did not follow the fix. Land OPS-25 first — both sides of that card touch the same files.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
