# Completion — Zalo unreachable-recipient handling + candidate name capture

## Task record

- Task: (1) Fix "Gửi lỗi" on Zalo OA sends (`user_id is invalid`); (2) capture
  candidate name into lead info, options A+B+C as approved in-session.
- Scope: OA send error classification, conversation finalizer side effects,
  profile-name gate widening + blank-only persistence, Jev profile-name
  decision, ChatThread failure reason.
- Files changed:
  - `backend/app/shared/application/outbound.py`
  - `backend/app/services/zalo_oa_service.py`
  - `backend/app/services/conversation/unreachable.py` (new)
  - `backend/app/services/conversation/send_claim.py`
  - `backend/app/services/conversation/recruiter_path.py`
  - `backend/app/recruitment/infrastructure/service_adapters.py`
  - `backend/app/services/lead/normalizers.py`
  - `backend/app/recruitment/application/ports.py`
  - `backend/app/graph/decisions.py`, `backend/app/graph/ports.py`,
    `backend/app/graph/runner.py`
  - `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx`
  - Tests: `tests/test_zalo_oa_service.py`, `tests/test_user_unreachable_side_effects.py` (new),
    `tests/test_lead_gender_guard.py`, `tests/test_graph_runner_turn.py`,
    `tests/test_graph_decisions.py`, `tests/test_lead_extraction.py`,
    `tests/test_graph_factories.py`, `tests/test_runtime_surface_inventory.py`
- Instructions retrieved: root AGENTS.md, frontend/AGENTS.md, ak:debug skill.
- Approval required: Jev decision-surface change (option C) — approved by user
  in-session ("also option C pls implement"); profile-name persistence policy
  (option B) — approved in-session. No protected-path files touched.
- Approval evidence: user messages in this session.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Zalo: -201 → `user_unreachable`, side effects on finalize, FE reason label. Name: gate accepts family-last, blank-only persistence (B), Jev question + runner persistence (C). |
| Diff is limited to the approved scope | PASS | `git status --short` — only files listed above. |
| Protected operations were avoided or approved | PASS | No alembic versions, no webhook/auth/ratelimit/core files, no dependency manifests, no deploy. |
| Focused tests/checks pass | PASS | `pytest tests/test_user_unreachable_side_effects.py tests/test_lead_gender_guard.py tests/test_zalo_oa_service.py tests/test_graph_decisions.py tests/test_lead_extraction.py tests/test_graph_runner_turn.py` → 298 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest tests --ignore=tests/integration` → 2324 passed, 24 skipped; `pytest tests/integration` → 131 passed; frontend `npm run test:unit:app` → 593 passed. |
| Lint passes for affected code | PASS | `ruff check app tests` → all passed. (`ruff format` is not clean at HEAD; pre-existing style left untouched.) |
| Type checking passes for affected code | PASS | frontend `npm run typecheck` clean; backend has no mypy gate. |
| Build/import validation passes for affected code | PASS | Full import via pytest collection; live probe script executed against prod read-only APIs during diagnosis. |
| Security and privacy impact reviewed | PASS | No PII logged (name values never logged); Jev `profile_name` is already sent per-turn; unreachable note contains no candidate data. |
| Performance and async-I/O impact reviewed | PASS | Name question piggybacks the existing single Jev call; persistence is one blank-merge upsert on capture turns only; no new I/O on the send hot path beyond one SYSTEM-note insert per conversation (deduped). |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | New FE label is Vietnamese, mirrors existing `failureReasonLabel` contract; retry button unchanged. |
| Error handling and compatibility reviewed | PASS | Persistence/side-effects are best-effort try/except; reconcile `LIKE '%user_id is invalid%'` still matches (provider text preserved verbatim in error). |
| Documentation impact handled | PASS | Behavior change recorded here; no user-facing docs reference lead-name policy or OA send errors. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | Clean. |
| Final `git status --short` reviewed | PASS | 18 files, all in scope. |

## Verification coverage (UI contract)

| Claim | Rung | Evidence | Not covered |
|---|---|---|---|
| Failed OA sends store Zalo's verbatim "user_id is invalid" + side effects fire | DB/API VERIFIED (unit + integration suites); prod rows inspected (messages 3103/3054/3043…, all `chunk 1/1 failed: user_id is invalid`) | prod DB query output; new unit tests | Live redeploy not performed (needs approval); no UI click-through on the new FE reason label |
| Failing recipients rejected by Zalo API | DB/API VERIFIED | read-only `user/detail` probe from prod: failing ids → `-201 user_id is not valid`; working ids → data | — |
| Name capture end-to-end | DB/API VERIFIED (unit tests through adapter/runner seams; gate function live-checked) | pytest 2324+131; direct function run | Not verified against prod after deploy |

## Result

- Overall status: DONE_WITH_CONCERNS
- Remaining risks or follow-ups:
  1. **Root-cause split**: Zalo rejects 5 stored OA recipient ids with -201 on
     every send ever, while its own webhooks still deliver messages with those
     ids — strongly suggesting a second OA shares our webhook URL (the OA
     webhook deliberately runs without signature verification, see
     `app/api/webhooks.py`). Recommend: audit Zalo OA apps pointing at
     `/webhooks/zalo/oa` and/or add webhook origin verification.
  2. Not deployed — `make deploy` awaits approval.
  3. Jev degradation (Jev off/unreachable) leaves option C inert; options A+B
     still capture the deterministic cases.
