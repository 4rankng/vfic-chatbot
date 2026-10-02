---
id: FE-31
title: "Raw newline escape sequences visible in KB readonly textareas"
severity: low
area: frontend
labels: [frontend, visual, text-rendering]
effort: S
status: todo
column: TODO
opened: 2026-10-02
---

# FE-31 — Raw newline escape sequences visible in KB readonly textareas

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, visual, text-rendering

**Trạng thái:** TODO

## Problem

KB content in the readonly markdown textareas renders literal `\n` characters as visible text instead of actual line breaks. Example from the "Vị trí tuyển dụng" panel:

`summary: "Vị trí: Nhân viên lắp ráp cơ khí & điện tử (Chính thức).\nBộ phận sản xuất: QA, SMT, UI..."`

The raw KB source escapes are shown to the reader instead of being converted to line breaks, making the content harder to scan.

## Evidence

- https://bot.tingting.vip/#/projects — expanded "4P Electronics" project card, "Vị trí tuyển dụng" category panel (and other category panels), readonly markdown textareas
- Same in the expanded "AMTRAN" project card

## Impact

Cosmetic, readonly view only. KB text is harder to read; looks like a rendering bug to operators reviewing knowledge content.

## Suggested fix

Convert the `\n` escape sequences to real newlines before display in the readonly view (or render the stored markdown properly), so the textarea shows formatted text instead of raw source.

## Notes

Observed 2026-10-02 in the read-only visual audit (signed in as Frank Ng). No state was created, edited, or deleted.

---

_Opened 2026-10-02 from the read-only visual audit of https://bot.tingting.vip/#/projects. No code was changed by the audit; every claim is grounded in the observed UI locations above._
