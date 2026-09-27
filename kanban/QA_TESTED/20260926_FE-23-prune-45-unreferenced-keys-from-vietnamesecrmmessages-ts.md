---
id: FE-23
title: "Prune ~45 unreferenced keys from vietnameseCrmMessages.ts"
severity: low
area: frontend
labels: [frontend, i18n, dead-code]
effort: S
status: done
column: QA_TESTED
opened: 2026-09-26
---

# FE-23 — Prune ~45 unreferenced keys from vietnameseCrmMessages.ts

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, i18n, dead-code

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The post-sweep catalog carries a large set of keys no translate()/notify() call can ever reach. Whole blocks are orphaned: leftovers from pre-sweep pages (settings/theme/login screens rebuilt with hardcoded Vietnamese) and from duplicate resources.conversations takeover/release clusters that predate the top-level keys now in use.

## Evidence

- frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:173-187 — crm.settings block: zero translate() references anywhere in frontend/src
- frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:188-193 — crm.theme block unreferenced; :221-242 crm.auth block unreferenced (login pages hardcode Vietnamese instead)
- frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:165-171 — crm.navigation: only .overview is used (RecruitingCommandCenter.tsx:203); label/messages/projects/settings/performance/account are dead
- frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:36-43 — resources.conversations.takeover/release are unreachable duplicates of conversations.takeover/release (:154-161) and have diverged ('Tiếp nhận thất bại' vs 'Tiếp nhận hội thoại thất bại')
- frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:196-208,:248-251 — crm.profile.record_not_found, crm.common copy/copied/loading/load_failed, 'ra-auth'.auth.forgot_password have no local references

## Impact

~45 phantom keys imply coverage that does not exist: anyone localizing or auditing UI text must diff every key by hand, and the divergent takeover/release duplicates risk someone 'fixing' the live copy in the dead one. The catalog grows monotonically because nothing flags unreferenced keys.

## Suggested fix

Delete the dead subtrees (crm.settings, crm.theme, crm.auth, the six unused crm.navigation keys, crm.profile.record_not_found, crm.common copy/copied/loading/load_failed, resources.conversations.takeover/release, ra-auth pending a ra-core ForgotPasswordPage check). If the strings are wanted for upcoming pages, re-add them together with the consuming translate() call.

## Notes

Sweep-derived, not style: the catalog is the single translation source for ra-core/product strings, so unreferenced keys are dead code by definition here.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
