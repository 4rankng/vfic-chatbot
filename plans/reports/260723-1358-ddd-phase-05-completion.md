# Agent Completion Checklist

## Task record

- Task: Phase 5 — migrate conversation, channel, and messaging context
- Scope: Neutral ingress and delivery contracts, webhook composition, outbound
  recovery, realtime authorization, stable worker entrypoints, and architecture
  enforcement.
- Files changed: `backend/app/conversation_messaging/`,
  `backend/app/composition/conversation_messaging.py`, affected webhook,
  conversation, graph, realtime, worker, tests, and architecture decision docs.
- Instructions retrieved: Project `AGENTS.md`, Phase 5 plan, architecture,
  testing, and completion-checklist sources.
- Approval required: PASS — protected webhook and integration behavior changed.
- Approval evidence: User granted blanket approval and directed all pending
  items to be fixed, with OA credentials confirmed working in production.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Conversation/messaging application boundary, adapters, security checks, and compatibility entrypoints implemented. |
| Diff is limited to the approved scope | PASS | Final status and diff review cover only Phase 5 backend/docs/tests. |
| Protected operations were avoided or approved | PASS | Webhook and realtime security edits were explicitly approved; no schema, dependency, secret, or deployment-file edits. |
| Focused tests/checks pass | PASS | Phase 5 focused suites passed (421 tests before final neutral type cleanup). |
| Broader regression tests pass when shared behavior changed | PASS | Re-run after integration with newer main: `cd backend && .venv/bin/pytest -q`: 2189 passed, 23 skipped. |
| Lint passes for affected code | PASS | `cd backend && .venv/bin/ruff check .`: all checks passed. |
| Type checking passes for affected code | N/A | Backend has no separate configured typecheck gate; runtime Protocol contracts and import tests pass. |
| Build/import validation passes for affected code | PASS | Full backend collection/import and architecture tests passed. |
| Security and privacy impact reviewed | PASS | Bot and Facebook verification remain enforced; OA's access-token secret is not misused as a signing key, and its deferred-authenticity risk is documented. Realtime joins and presence fail closed under REST-equivalent viewer scope; logs remain content-free. |
| Performance and async-I/O impact reviewed | PASS | DB and provider I/O remains async; authorization adds one indexed viewer-scope query per active room/presence authorization. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes. |
| Error handling and compatibility reviewed | PASS | Stable RQ callable retained; item failures isolated; stale SENDING commands terminalize without resend; valid webhook ACK/backpressure behavior preserved. |
| Documentation impact handled | PASS | `docs/decisions/channel-authenticity-matrix.md` and DDD boundary decision updated. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Scoped search returned no matches. |
| Final `git diff --check` passes | PASS | `git diff --check` passed. |
| Final `git status --short` reviewed | PASS | All listed changes are Phase 5 artifacts; pre-existing stash retained for recovery until landing. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: A recruiter already subscribed while an entity
  is unassigned is re-authorized on active presence operations, but distributed
  Socket.IO does not immediately evict that historical subscription when another
  recruiter later claims the entity. New joins are denied and REST-equivalent
  room/presence authorization is enforced; assignment-triggered eviction is a
  separate distributed subscription-lifecycle enhancement.
