---
id: FE-32
title: "FE-30 fix fallout: \"Google Sheet\" heading renders twice in the empty state"
severity: low
area: frontend
labels: [frontend, visual, empty-state, regression]
effort: S
status: todo
column: TODO
opened: 2026-10-02
---

# FE-32 — FE-30 fix fallout: "Google Sheet" heading renders twice in the empty state

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, visual, empty-state, regression

**Trạng thái:** TODO

## Problem

The FE-30 fix (empty state for unlinked sheet) replaced the bare heading with a duplicated one. For a project with no linked Google Sheet:

- `ProjectKnowledgePanel.tsx` (~line 622, `RagCategoriesPanel`) renders the section with an `<h3>` "Google Sheet" + Link2 icon, immediately followed by `<ExternalSourceList/>`.
- `ExternalSourceList.tsx` (~line 311) renders `<EmptyState title="Google Sheet" description="Chưa liên kết Google Sheet cho dự án này."/>` when no rows exist.
- `page-shell.tsx` (~line 89): `EmptyState` always renders its `title` inside an `<h2>`.

Net result: **h3 "Google Sheet" stacked directly above h2 "Google Sheet"** + description — the section name appears twice in a row, with an h3→h2 heading-order inversion. One visual defect replaced another.

## Impact

Cosmetic. The empty state reads as a copy-paste glitch rather than an intentional state. Screen readers hit the inverted heading order too.

## Suggested fix

Don't repeat the section name in the `EmptyState` title — the parent already labels the section. E.g. title "Chưa liên kết", keeping the description as-is. (The single-page variant's title "Nguồn đồng bộ" does not duplicate its parent heading, so only the RAG branch needs the change.)

## Notes

Found 2026-10-02 in the read-only code audit. The FE-30 fix landed in source ~05:47 UTC, after the visual audit — prod may still show the old bare heading until deploy. No code was changed by the audit.

---

_Opened 2026-10-02 from the read-only code audit of /Volumes/LexarSSD/projects/chatbot. No code was changed by the audit; every claim is grounded in the file locations above._
