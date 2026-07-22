---
date: 2026-07-22
topic: one-page-project-activation
status: completed
---

# One-page Project activation

## Context

Rorze had a valid direct-context page, but the admin showed `Tắt`, `0 tài liệu`, and
`0/12`; the chatbot said it had no Rorze information.

## What happened

The project-owned knowledge-mode change created new Projects as inactive and added an
active-only chatbot resolver. The one-page save path persisted and validated the direct file,
but never activated its owning Project. The list also counted only RAG/versioned files and
displayed RAG feature readiness for direct-context Projects.

## Decisions

- A valid project-scoped one-page save activates an inactive Project in the same transaction as
  the direct-file write and audit events.
- Both the Project editor and the standalone Knowledge Base editor use that lifecycle for
  project-owned knowledge bases.
- Replacing knowledge on a deliberately disabled Project explains that the save will reactivate
  Agent use and requires confirmation.
- Ownership/load failures block saving instead of falling back to a lifecycle-bypassing path.
- Direct-context Projects count their one page as a document and show page-based readiness;
  RAG readiness remains category/feature based.

## Verification

- Pre-fix reproduction: `project.is_active=False`; post-fix: `project.is_active=True`.
- Backend blast-radius tests: 154 passed; affected Ruff checks passed.
- Frontend focused tests: 4 files, 11 tests passed; affected ESLint has no errors.
- Earlier clean-state broad runs: backend 1,784 passed and frontend 465 passed; production build
  passed. Later global TypeScript/test failures belong to concurrent external-source sync work.
- Adversarial review found no remaining Critical or High issue.

## Next

Existing already-saved inactive Projects need one deliberate page re-save or manual activation
after deployment. No deployment or live database mutation was performed. Add disposable-
PostgreSQL coverage later for transaction rollback and mixed RAG/direct document counts.
