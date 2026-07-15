---
name: qa-dev-environment
description: QA the Ting Ting local development environment, routes, responsive UI, workflows, and latency while recording findings without auto-fixing them.
---

# QA the development environment

Read `docs/qa-runbook.md` in full; it is the source of truth. Then:

1. Confirm the stack and health endpoints before testing.
2. Follow the runbook's approved test accounts and data-safety rules.
3. Sweep every listed route on desktop and 390×844 mobile.
4. Run the functional scripts and domain checks specified by the runbook.
5. Capture route timing and API latency.
6. Record evidence under `plans/qa-<date>/report.md` using the runbook issue
   format.

QA is read-only. Do not fix findings in the same run. Never expose credentials,
tokens, candidate PII, or message bodies in the report.

