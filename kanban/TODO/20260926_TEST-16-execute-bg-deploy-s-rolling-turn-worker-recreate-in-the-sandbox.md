---
id: TEST-16
title: "Execute bg_deploy's rolling turn-worker recreate in the sandbox instead of pinning it as script text"
severity: medium
area: testing
labels: [regression-test, deploy, bg-deploy]
effort: M
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-16 — Execute bg_deploy's rolling turn-worker recreate in the sandbox instead of pinning it as script text

**Severity:** medium · **Area:** testing · **Effort:** M · **Labels:** regression-test, deploy, bg-deploy

**Trạng thái:** TODO

## Problem

The 2026-09-26 bot-silence incident produced two deploy-path fixes: worker-chatbot is now rolled one replica at a time (rolling_recreate_service) and a turn_pipeline_check gate must pass before flip. test_deployment_makefile.py pins both only as raw script text, and its executed sandbox can never reach the rolling branch: the stubbed docker emits no `compose config` JSON, so declared_replicas falls back to 1 and rolling_recreate_service takes its documented '1 replica, single recreate' early return. The one-at-a-time replacement loop, the 180s healthy-budget wait, and the failure branches of both gates have never been executed by any test.

## Evidence

- backend/scripts/bg_deploy.sh:145-188 — rolling_recreate_service replaces stale replicas one at a time, waiting for a healthy replacement between replacements (the 09-26 outage fix)
- backend/scripts/bg_deploy.sh:69-71 — declared_replicas echoes 1 when `docker compose config` output is empty/invalid
- backend/tests/test_deployment_makefile.py:434-474 — the sandbox docker stub handles compose pull/up/ps/inspect/rm but has no `compose config` branch; unknown commands exit 0 with empty stdout, so declared_replicas always falls back to 1
- backend/tests/test_deployment_makefile.py:684-692 — the test comment admits the stub 'cannot report replicas' and only asserts the single-recreate command
- backend/tests/test_deployment_makefile.py:820-850 — the only rolling-path pins are source-text assertions (TURN_WORKERS literal, --no-recreate/--scale substrings, gate ordering)
- backend/scripts/bg_deploy.sh:291-297 — post-flip turn_pipeline_check gate; the sandbox stub answers `compose exec -T web-* python -m` with silent exit 0, so its failure/rollback branch is unexecuted

## Impact

The exact regression class that caused the 2026-09-26 bot-silence outage (a bug in stale_service_container selection, the wait/budget loop, the --scale bookkeeping, or the consumer-gate ordering) can ship while every text pin still passes. The deploy pipeline gate's failure path is equally unexecuted — a stalled pipeline would no longer abort the deploy and nobody would notice until prod.

## Suggested fix

Extend the sandbox docker stub to answer `docker compose config --format json` with a fixture declaring worker-chatbot deploy.replicas=3 (and compose ps -q with 3 cids). Then assert: (1) the deploy command sequence removes and recreates one replica at a time with --scale bookkeeping, never a single force-recreate of all three; (2) a rolled replica that never reports healthy triggers the 180s-budget warning plus the consumer-gate abort before flip_caddy.sh; (3) a non-zero turn_pipeline_check aborts into bg_rollback.sh. Keep or drop the 820-850 text pins once the behavior is executed.

## Notes

The incident fix itself is good and (pending OPS-25) written — this card is only the untested execution path.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
