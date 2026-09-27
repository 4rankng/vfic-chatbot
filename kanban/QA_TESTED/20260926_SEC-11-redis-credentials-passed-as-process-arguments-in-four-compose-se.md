---
id: SEC-11
title: "Redis credentials passed as process arguments in four compose services and the redis healthcheck"
severity: low
area: security
labels: [security, ops, hygiene]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# SEC-11 — Redis credentials passed as process arguments in four compose services and the redis healthcheck

**Severity:** low · **Area:** security · **Effort:** S · **Labels:** security, ops, hygiene

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

REDIS_URL embeds the Redis password, and four services pass it as a command-line argument instead of the environment. Command lines are world-readable inside the container via /proc and are shown in full by `docker ps`/`docker inspect` on the host. worker-chatbot and worker-persistence in the same file demonstrate the intended pattern: read REDIS_URL from env_file. The redis healthcheck likewise embeds ${REDIS_PASSWORD} as an argv, duplicated into every container's inspect output.

## Evidence

- backend/docker-compose.yml:248 — worker-ingest `command: ["rq", "worker", "ingest", "--url", "${REDIS_URL}"]`
- backend/docker-compose.yml:271 — scheduler `command: ["rqscheduler", "--url", "${REDIS_URL}"]`
- backend/docker-compose.yml:305,335 — worker-followup and worker-maintenance repeat the `--url ${REDIS_URL}` pattern
- backend/docker-compose.yml:167-175 — worker-chatbot's command reads REDIS_URL from env_file instead; worker-persistence (:212+) does the same
- backend/docker-compose.yml:73-77 — redis healthcheck embeds `-a ${REDIS_PASSWORD}` in the inspectable command (redis-cli prints an -a warning on every probe)

## Impact

Anyone with docker visibility (or any process inside those containers) reads the production Redis password in plaintext from ps/proc despite the .env being mode 600. Consistent env-based handling also removes the two-conventions maintenance hazard.

## Suggested fix

Drop `--url ${REDIS_URL}` from the four commands — rq and rqscheduler default to the REDIS_URL environment variable, which env_file already provides. For the redis healthcheck, pass REDISCLI_AUTH via the service environment and use `redis-cli ping` (or accept --no-auth-warning). Verify with `docker inspect` that no credential appears in Args/Env of healthcheck definitions. Compose is a deployment file — approval-gated per AGENTS.md.

## Notes

Requires host/container-level access to exploit, hence low; carded because REDIS_PASSWORD handling was an explicit audit item and the safe pattern already exists in the same file.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
