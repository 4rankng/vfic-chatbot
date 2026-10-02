---
id: FE-33
title: "Hardcoded failed: \"jobs\" sentinel misnames the category in ingest empty-input failure"
severity: low
area: frontend
labels: [frontend, ingest, error-message, tech-debt]
effort: S
status: todo
column: TODO
opened: 2026-10-02
---

# FE-33 — Hardcoded `failed: "jobs"` sentinel misnames the category in ingest empty-input failure

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, ingest, error-message, tech-debt

**Trạng thái:** TODO

## Problem

`use-project-ingest.ts` (~line 253), in the `ingest()` empty-input guard (`writes.length === 0 && !sourceFile`):

```ts
setState({
  phase: "failed",
  failed: "jobs",
  message: "Tệp chưa có nội dung kiến thức có thể nạp. Bổ sung thông tin tuyển dụng rồi tải lại tệp.",
  activated: [],
});
```

The render site (`ProjectKnowledgePanel.tsx` ~line 270, `BriefIngestSection`):

```tsx
{state.failed
  ? `Chưa xác nhận hoàn tất «${PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}»`
  : "Chưa nạp được tệp"}
```

So a generic "no ingestible input" failure would render as **"Chưa xác nhận hoàn tất «Vị trí tuyển dụng»"** — wrongly naming the jobs category as the failed item. The message is doubly wrong: it mentions "tệp" (file) in a branch where there is no source file, and recruitment info for a non-category-specific failure. Looks like the sentinel was copy-pasted from the `useState("jobs")` default-selected category in `RagCategoriesPanel`.

## Impact

Currently latent, not live: both UI callers (`BriefIngestSection` in the RAG panel and in `MigrationSection`) always pass a file — `read()` returns early without one — so the guard is unreachable from the UI today. It's a landmine for the next caller that reaches this path, and the misleading message would send an operator debugging the wrong category.

## Suggested fix

Set `failed: null` in this branch so the render falls back to "Chưa nạp được tệp", and reword the message to not mention a file or recruitment (e.g. "Không có nội dung kiến thức để nạp.").

## Notes

Found 2026-10-02 in the read-only code audit. No kanban ticket covers ingest failure messaging. No code was changed by the audit.

---

_Opened 2026-10-02 from the read-only code audit of /Volumes/LexarSSD/projects/chatbot. No code was changed by the audit; every claim is grounded in the file locations above._
