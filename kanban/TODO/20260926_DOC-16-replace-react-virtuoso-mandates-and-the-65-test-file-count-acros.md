---
id: DOC-16
title: "Replace react-virtuoso mandates and the 65-test-file count across standards/ and docs/ checklists"
severity: medium
area: docs
labels: [documentation, tech-debt, standards]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# DOC-16 — Replace react-virtuoso mandates and the 65-test-file count across standards/ and docs/ checklists

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt, standards

**Trạng thái:** TODO

## Problem

The virtua-for-react-virtuoso migration (TECH.md:49 records react-virtuoso as removed) never reached seven checklist/standards/QA locations that still mandate the removed library, and the DoD still cites a test-file count from months ago. These are the normative completion/review gates agents are told to apply.

## Evidence

- standards/performance.md:136 — '**react-virtuoso** required for long lists: conversations, messages, bot runs'; frontend/package.json:73 lists virtua ^0.49.2 and no react-virtuoso exists in any manifest (TECH.md:49 states it was removed)
- standards/definition-of-done.md:72, standards/review-checklist.md:27, standards/ui-guidelines.md:75, standards/prompt-library/README.md:180 — all four mandate react-virtuoso for long lists
- standards/definition-of-done.md:40 — 'Backend: .venv/bin/pytest ... all 65 test files pass'; backend/tests holds 188 unit test files (plus ~15 integration)
- docs/qa-runbook.md:406-407 — '`conversations` and `bot_runs` use `react-virtuoso` (per docs/HLD.md)'; the runtime uses virtua VList (ChatThread.tsx)
- docs/code-standards.md:188-190 — correctly says 'Use virtua (VList)' but its parenthetical 'react-virtuoso is also in deps' is now false

## Impact

An implementer obeying standards/performance.md or ui-guidelines.md installs react-virtuoso — tripping AGENTS.md's dependency-change approval gate and reintroducing a deliberately removed dependency; the QA runbook verifies the wrong DOM; the '65 test files' figure makes the DoD test gate look satisfied at ~1/3 of the suite.

## Suggested fix

Sweep react-virtuoso → virtua across standards/performance.md:136, definition-of-done.md:72, review-checklist.md:27, ui-guidelines.md:75, prompt-library/README.md:180, qa-runbook.md:406-407, and drop the stale parenthetical at code-standards.md:189. Update definition-of-done.md:40 to 'all unit + integration tests pass' (drop the hardcoded count). Use TECH.md:49 as the wording source.

## Notes

Wave-1 docs work did not cover standards/; this is the residual.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
