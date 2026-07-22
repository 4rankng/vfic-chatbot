# Phase 1 DDD baseline and production cutover

**Date**: 2026-07-22 21:56
**Severity**: Medium
**Component**: Phase 1 DDD baseline, logging, scanner, deployment
**Status**: Resolved

## What Happened

Phase 1 landed as a DDD baseline and went through a blue-to-green, smoke-gated production cutover on release `b80f8573`. The rollout held, monitoring stayed clean, and the privacy-safe logging path stayed quiet under real traffic. The part that slowed this down was the upfront architecture scanner and PII logging review: the scanner was too noisy around literal string matches, and the logging review blocked until we proved we were not leaking message content or personal data.

We made one explicit hardening call: exact-literal scanner matches were treated as hard signals, but we tightened the scanner so it only flags dangerous literals instead of every incidental string-like token. That was the right tradeoff. The naive version would have kept drowning the review in false positives and made the whole check useless.

## The Brutal Truth

This was frustrating because the work was mostly correct, but the tooling made it feel suspicious until we forced it to be precise. The slow part was not the product change; it was proving to ourselves that the scanner and the logs were not lying. That is annoying, but it is also the kind of annoyance that prevents a much worse 2am incident later.

## Technical Details

- Release SHA: `b80f8573`
- Cutover: blue -> green, smoke-gated, with clean monitoring after the flip
- Logging review outcome: privacy-safe logging only, no message content or PII in the emitted path
- Scanner change: exact-literal matching was hardened to reduce false positives from incidental literals
- Remaining risk: commented TypeScript imports can still trigger future false positives if the scanner gets too literal again

## What We Tried

- Reviewed the architecture scanner output before release.
- Blocked on the PII logging pass until the emitted fields were verified as safe.
- Tightened exact-literal handling instead of broadening the ignore list.
- Ran the deployment through the blue/green smoke gate rather than taking a direct cutover.

## Root Cause Analysis

The blocker was not the baseline design itself. The root issue was that the scanner was over-sensitive and the review workflow was not yet calibrated to separate real data exposure from harmless literals. That created churn and almost turned a useful guardrail into background noise.

## Lessons Learned

- Exact-literal scanner rules must stay sharp or they become nonsense.
- Privacy-safe logging needs to be proven, not assumed.
- Commented imports in TypeScript are a future false-positive trap if scanner heuristics drift back toward naive matching.
- Smoke-gated blue/green cutovers are worth the extra ceremony because they make the release verifiable instead of merely deployed.

## Next Steps

- Keep the hardened scanner behavior in place and watch for regressions on literal-heavy files.
- Preserve the privacy-safe logging contract in the next phase.
- Assign follow-up ownership to whoever touches the scanner or TS import parsing next, before the false-positive problem grows again.
