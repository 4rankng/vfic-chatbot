---
date: 2026-07-18
session: facebook-oauth-dialog-host-fix
---

# Journal: Facebook OAuth dialog host fix

## Context

The Facebook OAuth start flow was generating the wrong dialog origin. We were sending users to `graph.facebook.com/v25.0/dialog/oauth`, which looks plausible until Meta actually tries to resolve the dialog endpoint and rejects it. The Graph API host is still correct for API calls, but the OAuth dialog itself has a different origin.

## What Happened

- Fixed the OAuth start URL so the dialog opens on `www.facebook.com` while Graph API requests remain on `graph.facebook.com`.
- Kept query string encoding explicit with `urlencode` instead of relying on ad hoc concatenation.
- Added tests that pin every required OAuth parameter and verify the start endpoint shape so this cannot drift back into the same mistake.

## Evidence / Root Cause

The bad URL triggered Meta `GraphMethodException` `code 100` `subcode 33` with object `dialog`. That is the clue that matters: the request was aimed at the wrong host for the OAuth dialog, not that Meta was randomly failing.

The regression was introduced in `9fec8adf` and exposed by `e6fa8b36`. In other words, the bug was already baked into the generated URL path before the later change made it visible enough to trip the flow reliably. The frustrating part is that this was a tiny string-level mistake with outsized blast radius.

## Decision / Fix

The fix was to separate responsibilities cleanly:

- `www.facebook.com` for the OAuth dialog entrypoint.
- `graph.facebook.com` for Graph API calls.
- `urlencode` for parameter construction so the client ID, configuration ID,
  redirect, state, and scope stay intact.

I rejected the tempting shortcut of “just patch the failing test” because that would have preserved the broken host assumption and guaranteed a repeat incident.

## Verification

- 42 OAuth tests passed.
- 72 Messenger backend-focused tests passed.
- 10 frontend Messenger tests passed.
- Full backend suite: `1592 passed, 19 skipped`.
- Ruff was green.
- Review score was `10/10`.

## Next

Keep the host split explicit in code and tests. If the OAuth builder changes again, the first check should be whether the dialog origin is still `www.facebook.com`, not whether the URL merely looks Facebook-shaped.
