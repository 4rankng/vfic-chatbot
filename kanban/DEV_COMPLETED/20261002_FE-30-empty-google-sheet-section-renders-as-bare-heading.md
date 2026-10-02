---
id: FE-30
title: "Empty Google Sheet section renders as a bare heading on projects page"
severity: low
area: frontend
labels: [frontend, visual, empty-state]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-10-02
---

# FE-30 — Empty Google Sheet section renders as a bare heading on projects page

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, visual, empty-state

**Trạng thái:** TODO

## Problem

On the projects page, when a project has no linked Google Sheet, the "Google Sheet" section inside the expanded project card renders as just a heading with a link icon and absolutely no content below it. It looks unfinished — like a broken or half-rendered panel. Projects with a linked sheet (e.g. LG-DISPLAY) show the full sync block: sheet URL, "Tự động mỗi ngày 24h", "Đồng bộ gần nhất: ...", row count, and the "Đồng bộ ngay" / "Xóa nguồn đồng bộ" buttons.

## Evidence

- https://bot.tingting.vip/#/projects — expanded "4P Electronics" project card, bottom of the KB region: "Google Sheet" heading with link icon, empty below
- Same on the "Samsung SDS" project card
- Contrast: "LG-DISPLAY" expanded card shows the complete sync content block

## Impact

Cosmetic. Operators may read the bare heading as a failed or broken sync panel rather than "no sheet linked yet".

## Suggested fix

When no sheet is linked, render an explicit empty state under the heading instead of nothing — e.g. "Chưa liên kết Google Sheet" plus the existing link/connect action — so the section reads as intentional.

## Notes

Observed 2026-10-02 in the read-only visual audit (signed in as Frank Ng). No state was created, edited, or deleted.

---

_Opened 2026-10-02 from the read-only visual audit of https://bot.tingting.vip/#/projects. No code was changed by the audit; every claim is grounded in the observed UI locations above._
