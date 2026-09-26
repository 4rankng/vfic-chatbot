---
id: TEST-18
title: "Engage the backend coverage ratchet: fail_under is still 0 so the CI 'coverage gate' cannot fail"
severity: low
area: testing
labels: [coverage, ci, ratchet]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-18 — Engage the backend coverage ratchet: fail_under is still 0 so the CI 'coverage gate' cannot fail

**Severity:** low · **Area:** testing · **Effort:** S · **Labels:** coverage, ci, ratchet

**Trạng thái:** TODO

## Problem

The backend coverage gate is labeled as a gate but cannot fail: .coveragerc sets fail_under = 0 with a comment promising the first CI run's measured number becomes a never-lowered ratchet floor. CI has run repeatedly since (wave 1 close plus the 09-26 deploys), yet the floor is still 0 — backend coverage can regress to any number without a red build.

## Evidence

- backend/.coveragerc:14-17 — 'Report-only for now: no fail_under yet. The first CI run's measured number becomes the ratchet floor; raise it only, never lower.' followed by fail_under = 0
- .github/workflows/quality-gates.yml:61-62 — step 'Backend unit tests (coverage gate)' runs pytest --cov, which cannot fail on coverage while fail_under=0
- frontend/vitest.config.ts:19-53 — the frontend counterpart is a real ratchet: thresholds 67/55/57/68 whole-tree plus per-file 80% floors

## Impact

A PR deleting tests or gating new graph/services code behind untested paths keeps the 'coverage gate' step green. The two-day-old promise in the comment is already stale, so the ratchet, if never raised, becomes permanent dead config.

## Suggested fix

Run the backend unit lane once with --cov, read the measured total, set backend/.coveragerc fail_under to that number minus ~1pt (the same absorption margin the frontend floors use), and delete the 'Report-only for now' comment. Optionally echo the total in the CI step log so the next raise is a one-line diff.

## Notes

CI files are deployment-adjacent — the one-line .coveragerc change is the safe half; the workflow needs no edit.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
