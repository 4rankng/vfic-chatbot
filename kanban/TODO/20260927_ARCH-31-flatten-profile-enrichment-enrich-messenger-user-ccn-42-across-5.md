---
id: ARCH-31
title: "Flatten profile_enrichment.enrich_messenger_user: CCN 42 across 5 nesting levels"
severity: medium
area: architecture
labels: [nested-complexity, backend]
effort: M
status: todo
column: TODO
opened: 2026-09-27
---

# ARCH-31 — Flatten profile_enrichment.enrich_messenger_user: CCN 42 across 5 nesting levels

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** nested-complexity, backend

**Trạng thái:** TODO

## Problem

profile_enrichment.py is one of the worst-maintained production services (maintainability 1.7, file score 1.85/10, weighted deficit 3,001). Its core enrich_messenger_user method (:424) reaches CCN 42 across 5 nesting levels: the messenger profile fetch, field mapping, and persistence decisions are stacked in nested conditionals instead of guard clauses.

## Evidence

- backend/app/services/profile_enrichment.py — 581 lines, maintainability 1.7, score 1.85/10 (repowise get_health production scope)
- backend/app/services/profile_enrichment.py:424 — enrich_messenger_user: CCN 42, nesting depth 5 (repowise nested_complexity biomarker)

## Impact

The enrichment path runs on every inbound messenger contact; each new profile field or provider quirk has to be threaded through the same nested ladder, and the depth makes the failure branches effectively untestable in isolation.

## Suggested fix

Convert the nesting to guard clauses and extract the per-field mapping into small pure helpers. Keep REL-05's gender-blank fix (already QA_TESTED in this file) intact — its regression test must keep passing untouched.

## Notes

REL-05 (lead gender TOCTOU) landed in this file; coordinate the refactor with its regression test.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
