---
id: FE-08
title: "The no-explicit-any rule is enforced only for flat globs and never for atomic-crm"
severity: medium
area: frontend
labels: [tech-debt]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-08 — The no-explicit-any rule is enforced only for flat globs and never for atomic-crm

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** tech-debt

**Trạng thái:** DEV_COMPLETED

## Problem

`no-explicit-any` is set to `error` only for three flat globs, so `src/components/admin/layout/**` and `src/components/admin/form/**` are not covered, and 31 files inside the covered set neutralise the rule with a file-level disable. `src/components/atomic-crm/**` — 62k LOC of product code — has no rule at all, and the two `as unknown as` casts on `useDataProvider()` sit at the exact seam where conversation mutations are dispatched.

## Evidence

- `frontend/eslint.config.js:56-62` — `@typescript-eslint/no-explicit-any: error` is applied to a flat-glob file set (admin/, hooks/, lib/), which does not reach nested admin subdirectories.
- 31 admin files disable the rule at file level (`admin/autocomplete-input.tsx:1`, `admin/boolean-input.tsx:1`, `admin/bulk-delete-button.tsx:1`, `admin/edit-guesser.tsx:1`, `admin/filter-form.tsx:1`, `admin/list-guesser.tsx:1`, `admin/image-field.tsx:1`, `admin/number-field.tsx:1`, `admin/record-field.tsx:1`, …) plus ~20 line-level disables.
- `frontend/src/components/atomic-crm/**` is unguarded by any no-any rule; in practice it is clean — a `: any|as any|as unknown as|@ts-ignore|@ts-expect-error` grep over the product tree returns only 4 real sites, the rest being test-only fetch mocks.
- `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:371` and `conversations/presentation/use-conversation-actions.ts:48` — the two `as unknown as` casts bypass the typed `CrmDataProvider` contract.
- 4 `@ts-expect-error` remain, all in admin/: `file-field.tsx:49`, `image-field.tsx:42`, `reference-array-field.tsx:135`, `reference-many-field.tsx:105`; there are zero `@ts-ignore`/`@ts-nocheck` in the tree.

## Impact

The stated standard ("no any in admin/, hooks/, lib/") is met only in the letter, since the disables are explicit, and is unenforced for three quarters of the codebase. The two `as unknown as` casts bypass the typed provider contract where conversation mutations are dispatched.

## Suggested fix

Change the globs to `**` form (`src/components/admin/**/*.{ts,tsx}`) and move the shared no-any set into the root config. Replace the two `as unknown as` casts with a properly typed `CrmDataProvider` that includes `setConversationMode`/`sendConversationReply`, and either type the RA guesser files out or delete them after checking consumers.

## Evidence log

- f81c1042 — `no-explicit-any` scope made recursive and extended to `src/components/atomic-crm/**` (previously unguarded, 62k LOC); the product tree lands with zero new violations.
- The 31 vendored `admin/` files keep their explicit file-level disables by decision — they are a copy-paste dependency and rewriting their type signatures is not worth the regression risk.
- The two `as unknown as` casts at the conversation-mutation seam are replaced by one real `CrmDataProvider` type, so dropping a provider method is now a compile error.
- Verified: `npm run lint` 0 errors, `npm run typecheck` clean, provider/chat tests 28 pass.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
