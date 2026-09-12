---
name: ak:sequential-thinking
description: Apply step-by-step analysis for complex problems with revision capability. Use for multi-step reasoning, hypothesis verification, adaptive planning, problem decomposition, course correction.
user-invocable: true
when_to_use: "Invoke for multi-step reasoning with revisions."
category: utilities
keywords: [reasoning, step-by-step, analysis]
license: MIT
argument-hint: "[problem to analyze step-by-step]"
metadata:
  author: agentkit
  version: "1.0.2"
---

# Decision and evidence log

Use for a difficult decision or investigation requiring revised hypotheses and observable
checks. Routine questions do not need a scaffold. Keep private reasoning private; report a
concise decision summary rather than numbered thoughts or an internal reasoning transcript.

Record only useful state:
- Candidate explanations or options and the constraint each must satisfy.
- Observations that support or rule out a candidate, with source/test evidence.
- Chosen action and its concise rationale.
- Remaining uncertainty and the next discriminating test, if one is needed.

Revise a conclusion when new evidence warrants it. Stop when the decision is supported and
critical constraints are checked, or identify the missing evidence; zero uncertainty is not
required. Mechanical output constraints should be checked on the final artifact.

## Resources

Load `references/core-patterns.md` for revising the log, or the matching
`references/examples-api.md`, `references/examples-debug.md`, or
`references/examples-architecture.md` for an example. Advanced decision cases use
`references/advanced-techniques.md` or `references/advanced-strategies.md`.
Legacy optional scripts retain their input schema for existing users; use them only when
that structured record is explicitly needed, never to require a thought transcript.
