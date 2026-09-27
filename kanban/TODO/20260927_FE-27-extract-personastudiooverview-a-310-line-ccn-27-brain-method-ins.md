---
id: FE-27
title: "Extract PersonaStudioOverview: a 310-line CCN-27 brain method inside PersonaList.tsx"
severity: medium
area: frontend
labels: [brain-method, personas]
effort: M
status: todo
column: TODO
opened: 2026-09-27
---

# FE-27 — Extract PersonaStudioOverview: a 310-line CCN-27 brain method inside PersonaList.tsx

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** brain-method, personas

**Trạng thái:** TODO

## Problem

PersonaList.tsx (782 lines) defines PersonaStudioOverview (:215) as a single roughly 310-line component with CCN 27 — repowise's brain-method biomarker for the file — and renders it once at :748. The component carries the studio overview's layout, summary metrics, and list composition in one body.

## Evidence

- frontend/src/components/atomic-crm/personas/PersonaList.tsx — 782 lines, score 3.4/10 (repowise get_health production scope)
- frontend/src/components/atomic-crm/personas/PersonaList.tsx:215 — PersonaStudioOverview: ~310 lines, CCN 27, defined inline
- frontend/src/components/atomic-crm/personas/PersonaList.tsx:748 — the single render site
- repowise graph: PersonaList.tsx reaches 49 dependents (transitive; 4 direct importers by grep)

## Impact

The studio overview is the personas landing surface; every addition lands in the same 310-line body, and the file's 49-dependency reach means review noise spreads across the personas area.

## Suggested fix

Extract PersonaStudioOverview (and any sub-blocks it already names) into personas/presentation/ per the house domain/application/presentation layout, keeping props narrow and the single render site in PersonaList. The existing PersonaList.mobile-layout.test.tsx must pass unchanged.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
