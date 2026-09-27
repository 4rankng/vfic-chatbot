---
id: ARCH-32
title: "Flatten zalo_bot_service._split_long_plain_text: 5-level nesting in the channel's message splitter"
severity: low
area: architecture
labels: [nested-complexity, zalo]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-27
---

# ARCH-32 — Flatten zalo_bot_service._split_long_plain_text: 5-level nesting in the channel's message splitter

**Severity:** low · **Area:** architecture · **Effort:** S · **Labels:** nested-complexity, zalo

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

zalo_bot_service.py (666 lines, file score 2.35/10) splits outbound Zalo messages through _split_long_plain_text (:322), which nests 5 levels deep while resolving the length-vs-chunk tradeoff. The splitter is shared by every text reply the Zalo channel sends.

## Evidence

- backend/app/services/zalo_bot_service.py — 666 lines, score 2.35/10 (repowise get_health production scope)
- backend/app/services/zalo_bot_service.py:322 — _split_long_plain_text: nesting depth 5 (repowise nested_complexity biomarker), called at :439

## Impact

Every Zalo reply passes through the ladder; a boundary mistake here silently truncates or over-splits customer-visible messages, and the nesting makes the boundary cases hard to see let alone test.

## Suggested fix

Rewrite with guard clauses (return the unsplit text early, then one loop over paragraph/sentence/word fallbacks) and extract the deepest branch into a named helper. Add boundary tests at the exact chunk limits before touching it.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
