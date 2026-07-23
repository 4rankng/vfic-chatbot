# Candidate display-name overwrite fix

**Date**: 2026-07-23 20:46
**Severity**: High
**Component**: candidate extraction, lead context, and recruiter candidate profile panel
**Status**: Resolved

## What Happened

The assistant overwrote the candidate's name with the question text, so `CTY ở đâu vậy` replaced `Hùng` in the lead data. The deferred LLM patch was winning unconditionally, which meant a late guess could stomp a higher-confidence identity that was already present in the conversation context.

We fixed the authority boundary instead of trying to paper over the symptom. The system now trusts a high-confidence OA display-name context to avoid asking again when the label is clearly attributable, but it still treats ambiguous labels as untrusted. Persistence only accepts an explicit current self-introduction when provider identity is confirmed, and admin/recruiter profile editing now uses optimistic version checks so edits do not silently clobber newer data.

## The Brutal Truth

This was a dumb overwrite bug with real consequences. We had enough information to avoid the redundant question, yet the fallback logic still let a low-quality patch win and corrupt the record. That is exactly the kind of bug that feels tiny in code and expensive in the UI, because once a candidate name is wrong, every downstream screen looks flaky and nobody trusts the rest of the workflow.

## Technical Details

- Root failure: deferred LLM patch applied after extraction with no authority guard, so it could overwrite existing identity data.
- Guard added: high-confidence OA display-name context is treated as an avoid-ask signal, but ambiguous labels remain non-authoritative.
- Persistence rule: only an explicit current self-introduction is accepted when provider identity is confirmed.
- Admin/recruiter profile editing now carries an optimistic version to prevent silent lost updates.
- Verification: `2222` backend tests passed, `23` were skipped, and `572` frontend tests passed; lint, typecheck, and build all completed cleanly.

## What We Tried

- We first traced the overwrite through the extraction path to prove the LLM patch was the last writer.
- We rejected a regex-only fix because it would still let the wrong authority win.
- We rejected blindly disabling the deferred patch because the good path still needs to merge late context when it is actually authoritative.

## Root Cause Analysis

The root cause was broken write authority. We treated late model output like it was equally trusted, even when a higher-confidence candidate identity already existed. That made the system vulnerable to exactly the wrong kind of correction: a guess overwrote a known name because the code had no explicit priority rule.

## Lessons Learned

- Identity data needs an explicit authority order, not "last write wins."
- If a display label is not proven, it should reduce questions, not overwrite state.
- Profile edits need optimistic concurrency, otherwise two correct actions become one lost update.
- Once a field like candidate name is visible to users, overwrites are production bugs, not cosmetic issues.

## Next Steps

- Keep the authority guard in place for extraction and persistence paths.
- Watch for any other deferred patch path that still assumes it can overwrite canonical identity.
- Owner: recruitment/chatbot maintainers.
- Timeline: resolved in code; no deploy or commit was performed in this turn.
