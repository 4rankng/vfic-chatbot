---
id: FE-07
title: "Product code hardcodes Vietnamese, bypassing a catalog served by two competing providers"
severity: medium
area: frontend
labels: [tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-07 — Product code hardcodes Vietnamese, bypassing a catalog served by two competing providers

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

Every product god component hardcodes Vietnamese in JSX and never calls `useTranslate`, while `components/admin/` uses it in 20+ files. Action labels are duplicated with two different ellipsis glyphs, and two i18n providers exist: an English default that the runtime always overrides with the Vietnamese one, so `admin/` leaks English strings into a Vietnamese UI.

## Evidence

- `useTranslate` appears in only 2 product files — `conversations/presentation/ChatThread.tsx:374` and `integrations/ZaloIntegrationPage.tsx:974` — versus 20+ files under `components/admin/`.
- Hardcoded Vietnamese in JSX: `dashboard/RecruitingCommandCenter.tsx:184,277-279,337-339`; `conversations/presentation/ConversationList.tsx:265-281`; `performance/PerformancePage.tsx:45-47,113-118,150-190`; `personas/PersonaList.tsx:44-46,66-90`; `integrations/ZaloIntegrationPage.tsx:1908-1920,2010-2020`.
- Duplicated literals in three inconsistent forms: `"Đang lưu…"` (U+2026) at `dashboard/CandidateDataDialog.tsx:375`, `conversations/ConversationContextPanel.tsx:461`, `knowledge/KnowledgeSourceEdit.tsx:143` and `integrations/FacebookMessengerPageCard.tsx:110`; `"Đang lưu..."` (three dots) at `personas/PersonaForm.tsx:596`; and bare `"Đang lưu"` with no punctuation at `integrations/ZaloIntegrationPage.tsx:1914` and `:2014`. The same split exists for `"Lưu thay đổi"` (≥4 sites) and `"Thử lại"` (≥5 sites).
- `frontend/src/lib/i18nProvider.ts` is an English polyglot provider imported only as the default at `components/admin/admin.tsx:9`, while `App.tsx:3` and `components/atomic-crm/root/CRM.tsx:73` always supply the Vietnamese one.
- `frontend/src/components/admin/filter-form.tsx:408` renders English "Save current query..." inside the Vietnamese UI because `ra.saved_queries.*` has no catalog entry (`saved-queries.tsx:75` has the same gap).

## Impact

Two ellipsis glyphs and four copies of every action label make a wording fix an O(n) source edit, and `admin/` shows English micro-copy inside a Vietnamese product UI.

## Suggested fix

Add the ~40 missing micro-copy keys to `vietnameseCrmMessages` (`common.save_changes`, `common.retrying`, `common.retry`, `common.loading`, `common.load_failed`, `common.unsaved_changes`), move product strings onto `useTranslate`, and delete `frontend/src/lib/i18nProvider.ts` in favour of the Vietnamese provider as the admin default.

## Evidence log

- 7f28d2a8 — 91 catalog keys added (235 → 326), 26 components migrated onto `useTranslate`, one ellipsis form used consistently, and the `ra.saved_queries.*`/adjacent `ra.*` gaps filled so no English leaks into the Vietnamese UI.
- `leads/domain/candidateProfile.ts` moved from `label: string` to `labelKey: string`, so one field definition feeds both the candidate dialog and the conversation context panel.
- Verified: the component tests assert Vietnamese output, so their passing is the evidence wording survived; full suite 595 tests green.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
