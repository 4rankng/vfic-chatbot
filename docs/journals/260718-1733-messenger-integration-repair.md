---
date: 2026-07-18
session: messenger-integration-repair
---

# Journal: Messenger integration repair

## Context

The Settings UI had a Messenger section that was either missing from the visible navigation or failed to resume the OAuth flow cleanly after Meta redirected back. The disconnect path also depended on the wrong identifier shape. The result was a broken admin experience: Messenger looked half-built, and the flow leaked too much coupling between UI state and backend authority.

## What Happened

- Registered `FacebookMessengerIntegrationPage` in the Settings navigation for both desktop and mobile, and made the hash callback reopen that section automatically.
- Switched the OAuth callback from Bearer-authenticated JSON to a one-time state redirect flow because the provider callback cannot carry the app JWT.
- Bound OAuth state and flow capsules to both `admin_id` and `token_version`, consumed them atomically with Redis `GETDEL`, and made completion single-use.
- Changed disconnect to resolve the active Page server-side instead of trusting a masked suffix from the UI.
- Treated provider acknowledgement as strict: `subscribe_app_to_page()` now accepts only an explicit `success: true`.
- Made unsubscribe best-effort so a provider failure does not keep a local Page falsely active.

## The Brutal Truth

This was annoying because the bug was not one thing. It was a chain of small contract mismatches that made the integration feel flaky and unfinished. The UI, callback, and backend were each slightly wrong in a different way, which is exactly how you waste time debugging a feature that should have been boring.

## Technical Details

- The Messenger UI was not consistently reachable from `/settings`.
- The OAuth callback needed redirect-based routing, not an admin Bearer header.
- The disconnect API should not have depended on a client-supplied `page_id`.
- A stale `token_version` now fails the flow with `session_changed` instead of replaying an old capsule.
- `subscribe_app_to_page()` now fails closed unless Meta explicitly returns `{"success": true}`.

## What We Tried

- Added navigation and callback recovery tests for the frontend.
- Added backend lifecycle tests for state replay, invalid admin/session, provider failures, and safe unsubscribe behavior.
- Verified the final flow with focused backend tests, targeted frontend tests, Ruff, lint, typecheck, and production build.

## Root Cause Analysis

The root cause was not “Messenger missing” in the abstract. The real defects were: the UI section was not wired into the settings navigator; the callback path still assumed a normal authenticated API call; disconnect trusted the wrong identifier boundary; and the flow lifecycle did not enforce atomic, session-bound consumption. That made the integration brittle, replayable, and easy to strand.

## Lessons Learned

- Browser redirects are not API calls; design the callback around that reality from the start.
- Never let the UI own the authority key if the backend can derive it.
- Single-use OAuth flows must be atomic or they will be replayed.
- If a provider acknowledgement is ambiguous, fail closed and keep the error generic.

## Next Steps

- Treat production Meta connection as a readiness-gated rollout, not an automatic ship.
- Run a real canary with a live Facebook Page only after explicit approval.
- Keep the disconnect and OAuth regression tests in place; they are now the only thing preventing this from drifting back into a broken state.

