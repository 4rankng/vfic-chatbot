---
id: TEST-23
title: "Give PersonaForm.tsx a behavioral test file: 609 lines, 58 dependents, zero paired tests"
severity: medium
area: testing
labels: [untested-hotspot, personas]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-27
---

# TEST-23 — Give PersonaForm.tsx a behavioral test file: 609 lines, 58 dependents, zero paired tests

**Severity:** medium · **Area:** testing · **Effort:** S · **Labels:** untested-hotspot, personas

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

PersonaForm.tsx is the worst performer in the repowise production scan (file score 1.65/10) and its untested-hotspot biomarker is explicit: a hotspot with no paired test file and no coverage data, reaching 58 transitive dependents. The personas directory carries layout/assignments/list tests, but nothing exercises the create/edit form's validation or save behavior.

## Evidence

- frontend/src/components/atomic-crm/personas/PersonaForm.tsx — 609 lines, score 1.65/10, untested_hotspot: no paired test file, 58 transitive dependents (repowise get_health production scope)
- frontend/src/components/atomic-crm/personas/ — directory tests cover layout regressions, PersonaAssignments, and PersonaList mobile layout; none cover PersonaForm (verified 2026-09-27)

## Impact

FE-27-style refactors of the personas surface have no safety net for the form; validation or save regressions reach QA (or users) undetected, and the file's deficit will keep ranking it worst-in-repo until behavior is pinned.

## Suggested fix

Add PersonaForm.test.tsx covering: required-field validation errors, dirty-state gating of the save action, the happy-path save call with its payload, and the save failure path. Assert user-visible Vietnamese strings so the test doubles as copy coverage.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
