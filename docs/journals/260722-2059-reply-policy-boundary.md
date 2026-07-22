# Reply policy boundary leak

**Date**: 2026-07-22 20:59
**Severity**: High
**Component**: `backend/app/graph/safety.py`, `backend/app/graph/runner.py`, `backend/app/graph/ports.py`, `docs/system-architecture.md`
**Status**: Resolved

## What Happened

Production leaked provider reasoning into a user-visible reply. The direct-context lane was the bypass: it could hand raw provider text to the response flow before every user-visible lane converged on `ReplyPolicyPort.finalize`, so the malformed `<think>` opener case had a path to escape.

The review finding was the important warning sign. It caught that malformed opener handling needed to fail closed, not merely strip a happy-path `<think>...</think>` block. The fix converged user-visible output through `ReplyPolicyPort`, with `DeterministicReplyPolicy` as the default implementation, so the runner no longer owns ad hoc reply cleanup.

## The Brutal Truth

This was avoidable. We already had the architecture decision in ADR-0010 telling us provider reasoning is sensitive and admin-only, but the implementation still drifted into piecemeal filtering. That is exactly how leaks survive code review: the policy is “everywhere” until it is nowhere. It is frustrating because the failure mode was stupidly specific and still expensive to reason about after the fact.

## Technical Details

- Review found malformed opener cases that had to fail closed: `"<think\n..."`, `"<think internal..."`, and `"< think>..."`.
- `strip_think_reasoning()` now removes both completed and truncated reasoning before any user-visible send path.
- `DeterministicReplyPolicy.finalize()` is the converged pre-send gate; admin reasoning trace preservation stays separate and intact.
- Verification: `109/109` tests passed in `backend/tests/test_graph_safety.py` and `backend/tests/test_graph_runner_turn.py` (`pytest -q` completed cleanly in 1.58s).
- Production deployment landed on green at commit `2da4ea3d`, with smoke passing, and rollback remained pinned to blue tag `88fb63c7`.

## What We Tried

- We first fixed the obvious `<think>...</think>` path.
- We then added regressions for malformed openers so the bug could not quietly return.
- We rejected scattering extra cleanup into the runner because that would duplicate policy logic and still miss other reply sources.

## Root Cause Analysis

The root cause was a broken boundary. Safety and reply finalization were not converged at the point where all user-visible outputs pass through, so reasoning stripping was easy to get wrong and hard to audit. The malformed opener finding proved the weak spot: if the opener is malformed, the system must not guess.

## Lessons Learned

- Safety belongs at one converged pre-send boundary, not in scattered cleanup code.
- Malformed or truncated reasoning markers must fail closed.
- Admin trace reasoning and user-visible reply handling are separate concerns and must stay that way.
- If a policy can be bypassed by a parser edge case, the boundary is wrong.

## Next Steps

- Keep `ReplyPolicyPort` as the only place user-visible replies are finalized.
- Preserve admin-only reasoning traces exactly as documented in the architecture.
- Treat new reply sources or formats as boundary changes, not local string cleanup.
- Owner: bot graph maintainers. Timeline: now, before the next safety-related change lands.
