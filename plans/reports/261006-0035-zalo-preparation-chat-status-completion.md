# Agent Completion Report — Zalo chat status while a candidate message is prepared

## Task record

- Task: Ensure that while the app prepares a message to send a candidate, the
  Zalo ecosystem sends its native chat status (`sendChatAction` → `typing`);
  then commit, push, and deploy to production.
- Scope: backend only, and only the preparation window that had none — a
  recruiter reply (fresh or retry) on the **Zalo Bot** channel. The bot turn
  already pulses (webhook ack → worker bridge → graph heartbeat), and Zalo OA /
  Facebook Messenger expose no typing operation (docs-verified 2026-09-30,
  `plans/reports/zalo-typing-260930-2240.md`). That report declined a
  turn-start registry call site as a duplicate; this change adds a different
  call site, in a window that had no heartbeat at all.
- Files changed: `backend/app/services/chat_status.py` (new),
  `backend/app/services/conversation/service.py`,
  `backend/tests/test_preparation_chat_status.py` (new),
  `backend/tests/test_runtime_surface_inventory.py` (snapshot),
  `backend/tests/test_conversation_service_composition.py` (pre-existing red),
  `docs/architecture/system-architecture.md`, `docs/product/codebase-summary.md`.
  7 files, +334/−3, two commits.
- Instructions retrieved: `AGENTS.md`; `docs/architecture/system-architecture.md`
  (§3 typing heartbeat); `docs/product/codebase-summary.md`;
  `docs/development/testing.md`; `docs/ops/deployment-guide.md` (read in full
  before deploying, per AGENTS.md); `standards/agent-completion-checklist.md`.
- Approval required: commit/push/deploy to production (AGENTS.md: never deploy
  unless asked).
- Approval evidence: user instruction in this session — “once done commit and
  push and deploy to prof”. Work done directly on `main` per AGENTS.md.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `pytest tests/test_preparation_chat_status.py tests/test_recruiter_oa_reply.py -q` → **11 passed**: pulse fires on the Bot channel *before* preparation starts (`order == ["status", "prepared"]`), same pulse on retry, no pulse (and no config resolution) for `zalo_oa`/`facebook_messenger`, a raising status never blocks the send, a stalled status is dropped at the timeout. |
| Diff is limited to the approved scope | PASS | `git diff --stat 171e22bf..HEAD` → 7 files, +334/−3: feature, its tests, the inventory snapshot, two docs, plus the unrelated pre-existing test fix below. No frontend, schema, or config change. |
| Protected operations were avoided or approved | PASS | No branch/PR/tag created; two commits on `main` (`cba81c54`, `aa1eeb7b`) as AGENTS.md directs. Deploy was explicitly requested. |
| Focused tests pass | PASS | Commands above (11 passed) and `pytest tests/test_runtime_surface_inventory.py -q` → passed after the snapshot update. |
| Broader regression tests pass when shared behavior changed | PASS | `make release-check` → exit 0 in 1271 s: backend lane (pyright + ruff + unit suite w/ coverage), frontend lane (audit/lint/typecheck/registry/coverage/build/smoke), data lane (migration reversibility walk + golden retrieval `golden_pass_rate_pct=100.0%`). No `RELEASE-CHECK FAILED` banner. |
| Lint passes for affected code | PASS | `backend/.venv/bin/ruff check .` → “All checks passed!” |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → “0 errors, 0 warnings, 0 informations” (the release gate's type scope; the change sits in `app/services/`). |
| Build/import validation passes for affected code | PASS | Release-check built the frontend and imported the backend suite; in the deployed container: `web-green python -c "from app.services.chat_status import ..."` → `import-ok app.services.chat_status`. |
| Security and privacy impact reviewed | PASS | No new secret read path — the token comes from the existing Redis-cached `resolve_zalo`. Only the chat id (already on the wire for every send) leaves the process. No message content or token in logs (debug lines carry `error_type` only). Nothing new is exposed at the edge. |
| Performance and async-I/O impact reviewed | PASS | One extra awaited HTTP request per Zalo-Bot recruiter send, bounded by `asyncio.wait_for(..., 2.0)` and swallowed on any failure; config lookup is `cached_zalo_config` (Redis). No new task, session, DB write, or heartbeat. Worst case adds ≤2 s to a recruiter send when the provider stalls — bounded and deliberate (cosmetic work is dropped, never blocking). |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change; the visible effect is Zalo's own native status in the candidate's chat. |
| Error handling and compatibility reviewed | PASS | `except Exception` swallows status failures but not `CancelledError` (BaseException on 3.12), so request cancellation still propagates. OA/Messenger return before any config resolution, so their behaviour is byte-identical. The bot-turn path is untouched — its own heartbeat still owns that window. |
| Documentation impact handled | PASS | `system-architecture.md` §3 bullet now records the preparation pulse and the per-channel limits; `codebase-summary.md` gains the module row. `node scripts/check-doc-links.mjs` → “Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve.” |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff 171e22bf..HEAD \| grep -E '^\+.*(TODO\|FIXME\|HACK)'` → no matches. |
| Final `git diff --check` passes | PASS | `git diff --check` → exit 0 (also a release-check prerequisite, clean worktree). |
| Final `git status --short` reviewed | PASS | Only `?? plans/reports/261006-0035-zalo-preparation-chat-status-completion.md` (this file) at review time; committed with this report. |

## Deployment evidence (requested separately from the gates)

- `make release-check` → passed (prerequisite, run before `make deploy`).
- `make deploy` → `bg_deploy done. active=web-green tag=aa1eeb7b` in 430 s:
  pre-migration dump + both image pushes green, 4/4 `worker-chatbot` replicas
  healthy through the roll, smoke gate `SMOKE OK` on all five probes, Caddy
  flipped to `web-green`, turn-pipeline gate `PIPELINE OK` (7 live
  `webhook_high` consumers, 0 awaiting reply, 0 stale PENDING), old
  `web-blue` stopped, frontend recreated at the same tag.
- Post-deploy: `GET https://bot.tingting.vip/health` →
  `{"status":"ok","env":"production"}`, frontend root HTTP 200,
  `ACTIVE_COLOR=green`, `PREV_COLOR=blue@171e22bf`, deployed module import OK.
- Rollback path if needed: `make -C backend rollback` (verified state: prev
  colour `blue` @ `171e22bf`).

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Worst case +2 s on a recruiter send if Zalo's `sendChatAction` stalls;
    bounded by design, status is dropped rather than blocking.
  - The outbox recovery sweep (stale/pending replay) deliberately has no pulse:
    it re-sends an already-prepared command, not a preparation window.
  - Zalo OA still cannot show a status (platform limitation, docs-verified
    2026-09-30); the only lever would be spending real OA messages as progress —
    a product decision, not implemented.
  - `cba81c54` fixed a test that was already red on `main` (the 1cf0138b
    duplicate-inbound guard awaited a plain `MagicMock`); no production code
    changed there.
  - GitHub reported 1 moderate Dependabot advisory on the default branch at
    push time — pre-existing and unrelated to this change.
