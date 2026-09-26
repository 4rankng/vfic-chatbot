---
id: OPS-23
title: "ops-alerts.sh docker checks are dead on arrival (missing IMAGE_TAG, relative ACTIVE_COLOR, unparseable Reclaimable)"
severity: medium
area: ops
labels: [ops, alerting, regression]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# OPS-23 — ops-alerts.sh docker checks are dead on arrival (missing IMAGE_TAG, relative ACTIVE_COLOR, unparseable Reclaimable)

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, alerting, regression

**Trạng thái:** TODO

## Problem

The sweep grew ops-alerts.sh into the host-side half of the alerting story, but its two docker-based checks cannot succeed as written. The /metrics probe invokes `docker compose exec` without IMAGE_TAG, so the `${IMAGE_TAG:?}` guard fails every subcommand and METRICS is always empty. Colour detection reads `cat ACTIVE_COLOR` relative to the process cwd — under the documented cron install the cwd is not /opt/vfic, so it always falls back to blue and would probe the idle colour after a cutover. The docker-reclaimable check pipes docker's '12.34GB (67%)' text into `numfmt --from=iec`, which errors into the `|| echo 0` fallback, so the >10GB warn can never trigger.

## Evidence

- scripts/ops-alerts.sh:57-58 — `docker compose -f /opt/vfic/docker-compose.yml exec -T "$WEB" python -c ...` with no IMAGE_TAG in the environment and `|| true` swallowing the failure into empty METRICS
- backend/docker-compose.yml:24-27 — header states every compose command fails loudly until IMAGE_TAG is exported, and gives the docker-inspect resolution recipe
- scripts/ops-alerts.sh:55 — `COLOR="$(cat ACTIVE_COLOR 2>/dev/null || echo blue)"` reads a relative path; the documented cron invocation at :19 runs from the cron cwd, never /opt/vfic
- scripts/ops-alerts.sh:46-48 — `numfmt --from=iec` on '12.34GB (67%)' errors to `|| echo 0`, so the disk warn can never fire
- scripts/ops-alerts.sh:19 — install line `* * * * * root /opt/vfic/scripts/ops-alerts.sh`; no Makefile or bg_deploy step ever copies the script to /opt/vfic/scripts (backend/Makefile:110,126 ship only bg_deploy/bg_rollback/flip_caddy)

## Impact

The host half of the alerting story reports 'could not read /metrics' (or nothing) every minute regardless of actual health, and after any green cutover would inspect the idle colour even if the other bugs were fixed. Permanent noise trains operators to ignore it — the pre-sweep 'nothing watches' state with extra steps.

## Suggested fix

`cd /opt/vfic` at the top of the docker section, resolve COLOR from `cat /opt/vfic/ACTIVE_COLOR`, and resolve IMAGE_TAG from the running container exactly as backup-droplet.sh:47-67 does, exporting it for the compose exec. Replace the numfmt parse with `docker system df --format '{{json .}}'` numeric fields (or strip non-numerics first). Ship the script in the Makefile deploy SCP lists when the cron wiring hold is picked up.

## Notes

Cron scheduling itself remains the known held item; this card is that the script cannot work even once scheduled. The in-stack metrics-watch service is unaffected.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
