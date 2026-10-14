# Completion record — 2026-10-15 prod findings fix (bot.tingting.vip)

- Task: fix the 5 findings from docs/chatbot-improvement-2026-10-14.md
  (recovery-sweep dead tick, MissingGreenlet realtime loss, swallowed-error
  escalation, dead rq-scheduler entries + broken lint/test gate, Postgres
  memory headroom) and deploy.
- Scope: backend realtime seam, knowledge recovery sweep, scheduler boot,
  observability counters, lint/test gates, release lane. Server-side memory
  limit change + deploy executed under the user's explicit deploy
  authorization ("deploy code fix").
- Files changed: 29 tracked files across 5 commits
  (f8e1c5dd, 8472bc2b, 2b32ffaf, a0c7471e, b67ee6e4).
- Instructions retrieved: AGENTS.md, docs/ops/deployment-guide.md §1/§3,
  docs/development/testing.md, standards/agent-completion-checklist.md.
- Approval required: deploy + production memory-limit change — both covered by
  the task instruction (USER-AUTHORIZED "deploy code fix"; finding 5 named
  explicitly with target value and rollback).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | findings 1–4 fixed + tested; finding 5 + deploy executed (see plans/qa-261015/deploy-evidence.md) |
| Diff is limited to the approved scope | PASS | 5 commits, all within the 5 findings; 9 unrelated pre-existing integration failures left untouched and filed (plans/qa-261015/integration-baseline-failures.md) |
| Protected operations were avoided or approved | PASS | deploy authorized in task; no git push of branches; work on main per repo workflow |
| Focused tests/checks pass | PASS | red/green proven per fix (stash-revert → tests fail with the prod error class → restore → green) |
| Broader regression tests pass when shared behavior changed | PASS | full unit suite 3946 passed / 28 skipped; integration lane 325 passed / 9 pre-existing baseline failures (proven identical on clean e74355be) |
| Lint passes for affected code | PASS | ruff with BLE enabled — "All checks passed!" (release-check backend lane, plans/qa-261015/release-check.log) |
| Type checking passes for affected code | PASS | uvx pyright app/graph — 0 errors; release-check lane exit 0 |
| Build/import validation passes for affected code | PASS | make release-check — backend/frontend/data lanes all exit 0 |
| Security and privacy impact reviewed | PASS | counters carry keys only, no PII; /metrics already unauthenticated-internal parity with existing reconcile counters; no secrets logged |
| Performance and async-I/O impact reviewed | PASS | eager load adds ≤2 SELECTs only on the create-path publish (previously a swallowed crash); sync Redis INCR matches existing worker-side counter precedent, fires only on degraded paths |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | no UI change |
| Error handling and compatibility reviewed | PASS | conversation_updated now never raises (strictly safer for every caller); recovery tick failure semantics unchanged (counter + re-raise); purge is best-effort |
| Documentation impact handled | PASS | deployment-guide §1 updated for the changed-surface lane; node scripts/check-doc-links.mjs — "32 paths and 4 make targets ... all resolve" |
| No new unlinked TODO/FIXME/HACK | PASS | grep of the diff adds none |
| Final git diff --check passes | PASS | clean (commit b67ee6e4 worktree) |
| Final git status --short reviewed | PASS | clean after commits |

## Result

- Overall status: PASS (code fixes + gates; deploy evidence in
  plans/qa-261015/deploy-evidence.md)
- Remaining risks or follow-ups: 9 pre-existing manual-lane integration
  failures (classified, filed); ops-alerts.sh cron still not installed on the
  droplet (recommended in review, outside this scope); metrics-watch container
  has no healthcheck (review also-observed, outside this scope).

## Fix-by-fix evidence summary

1. **Recovery sweep** — reproduced `AttributeError: 'coroutine' object has no
   attribute 'all'` against a real AsyncSession; fixed 3 missing awaits;
   async-faithful fake + full-sweep unit test + real-session integration test
   (all three legs). Red/green: stash-revert fails 3 tests with the prod error.
2. **MissingGreenlet** — reproduced on the create path (`contact.primary_channel`
   ValidationError, exact prod traceback shape); bus eager-loads before
   serialize, payload failures armored + counted; record_bot_pending loads
   before the sync schedule. Integration tests pin create-path + end-to-end
   record_inbound publishes. Red/green: stash-revert fails exactly the 2 new
   tests.
3. **Escalation counters** — app/core/incidents.py; increments at every armor
   catch; exported on /metrics; polled by ops-alerts.sh; 9 unit tests incl.
   metrics endpoint shape and script/counter lockstep guard.
4. **Dead ticks + gates** — purge_dead_ticks (importability-based) wired into
   web boot with 3 unit tests; 4 dead entries confirmed in prod Redis (one
   more than reported: decision_trace_retention); BLE enabled with all 22
   unlabeled catches audited and labeled; changed-surface integration lane
   added to release-check (RELEASE_INTEGRATION_FILES).
5. **Postgres memory** — server change executed last, evidence in
   deploy-evidence.md.
