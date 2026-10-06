# Completion — Messenger unreachable sends: terminal classification + channel-aware CRM copy

## Task record

- Task: Finish the Messenger send-failure work: (1) classify Meta code 551
  ("This person isn't available right now", prod-proven 2026-10-06 on PSID
  28606960018965816, conversation be9abd11-d004-478e-bd48-0112f878d7d5) as
  terminal `user_unreachable`; (2) give Messenger conversations the same
  once-per-conversation side effects Zalo OA already had (follow-up opt-out +
  system note); (3) make the CRM bubble failure copy channel-aware and stop
  offering "Thử lại" for permanently unreachable recipients.
- Scope: backend adapter classification + conversation side effects; frontend
  domain helper + bubble row + thread wiring + tests. Build on the (parallel,
  staged) structured-rejection work in `facebook_oauth.py` /
  `facebook_messenger.py` / `channels/types.py`; did not touch that session's
  extraction-reliability files.
- Files changed:
  - `backend/app/channels/providers/facebook_messenger.py` — 551 added to the
    recipient-unreachable classifier (subcode-agnostic).
  - `backend/app/services/conversation/unreachable.py` — per-channel note map
    (`oa`, `facebook_messenger`); channels without a `user_unreachable`
    producer stay untouched.
  - `backend/tests/test_facebook_messenger_adapter.py` — 551→user_unreachable
    pin with the production detail text.
  - `backend/tests/test_user_unreachable_side_effects.py` — Messenger first/
    repeat stamp pins; untouched-channel pin moved to `zalo_bot`.
  - `frontend/.../domain/reply-failure-messages.ts` — `isUserUnreachableError`
    + channel-aware `replyFailureReasonLabel`.
  - `frontend/.../presentation/ChatMessageRow.tsx` — `channelProvider` prop;
    retry withheld on unreachable; reason shown even when the bubble has text.
  - `frontend/.../presentation/ChatThread.tsx` — resolves the display channel
    once per conversation and passes it to every row.
  - `frontend/.../ChatThread.test.tsx` — 3 new pins (Messenger unreachable,
    Zalo unreachable, retryable rejection keeps the button).
  - `frontend/.../domain/reply-failure-messages.test.ts` — matcher + label pins.
- Instructions retrieved: root `AGENTS.md`, `frontend/AGENTS.md`,
  `standards/agent-completion-checklist.md`.
- Approval required: no (continuation of the user's "fix them all" instruction;
  root cause was already confirmed with the user).
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | 551 → `user_unreachable` (`facebook_messenger.py::_is_recipient_unreachable`); Messenger side effects (`unreachable.py::_CHANNEL_NOTES`); CRM hides retry + names the channel (`ChatMessageRow.tsx`, `reply-failure-messages.ts`) |
| Diff is limited to the approved scope | PASS | 9 files listed above; remaining dirty files in `git status` belong to the parallel extraction-reliability session and were not touched |
| Protected operations were avoided or approved | PASS | No deploy, commit, push, branch, or migration; models untouched |
| Focused tests/checks pass | PASS | `uv run pytest tests/test_facebook_messenger_adapter.py tests/test_user_unreachable_side_effects.py` → 41 passed; `npx vitest run …/ChatThread.test.tsx` → 36 passed |
| Broader regression tests pass when shared behavior changed | PASS | backend adapter+oauth+side-effects+composition+outbox+graph-runner → 323 passed; `tests/test_runtime_surface_inventory.py` → 5 passed; frontend conversations suite → 25 files / 217 passed |
| Lint passes for affected code | PASS | `uv run ruff check` (4 backend files) → "All checks passed!"; `npx eslint` (5 frontend files) → clean |
| Type checking passes for affected code | PASS | `npm run typecheck` → clean (after fixing `recruiter_id` to `"42"`); backend has no separate typecheck gate beyond tests/ruff in this repo's flow |
| Build/import validation passes for affected code | PASS | Vitest browser-mode renders the real `ChatThread`/`ChatMessageRow` (import + render validated); backend imports exercised by 323 passing tests |
| Security and privacy impact reviewed | PASS | No new IO surface; PSID already sanitized upstream by `_sanitize_graph_error_detail` (staged work); Vietnamese note contains no recipient identifiers |
| Performance and async-I/O impact reviewed | PASS | One extra `COUNT` query per unreachable finalization only (same as the existing Zalo path); `channelProvider` memoized once per conversation, flat prop keeps row memoization |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Reason is real text in the bubble (screen-reader reachable); retry withheld with an explanatory reason instead of a dead button; all copy Vietnamese |
| Error handling and compatibility reviewed | PASS | Side effects remain best-effort (pinned by `test_side_effect_failure_never_propagates`); unknown channels untouched (pinned via `zalo_bot`); dispatcher's existing `user_unreachable` handling reused, no new plumbing |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | Durable rationale lives in code comments at the classification sites (matching the parallel session's choice for the same feature); `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve" |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | `git diff --check` → no output |
| Final `git status --short` reviewed | PASS | Reviewed; my files are the 9 listed above, the rest belong to the parallel session staged/unstaged work |

## Result

- Overall status: DONE
- Remaining risks or follow-ups:
  - The frozenset is intentionally narrow; future Meta recipient-refusal codes
    should be appended at `facebook_messenger.py::_RECIPIENT_UNREACHABLE_CODES`
    (the structured `external_error` now records code/subcode to make that easy).
  - Redis recipient marks suppress sends for the TTL (7 days); an existing
    `user_unreachable` mark for the production PSID (if any) persists until expiry.
  - Not covered: real-browser click-through on the production conversation
    (verification was test-suite level); other roles/viewport permutations of the
    bubble copy (labels are channel-derived strings already pinned by unit tests).
