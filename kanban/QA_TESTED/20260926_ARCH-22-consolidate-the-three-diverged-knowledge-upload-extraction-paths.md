---
id: ARCH-22
title: "Consolidate the three diverged knowledge-upload extraction paths in knowledge/service.py"
severity: medium
area: architecture
labels: [duplication, knowledge]
effort: M
status: done
column: QA_TESTED
opened: 2026-09-26
---

# ARCH-22 — Consolidate the three diverged knowledge-upload extraction paths in knowledge/service.py

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** duplication, knowledge

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

Uploading a knowledge file has three near-identical extract wrappers and two format detectors that already disagree. file_extraction.py owns the permissive detector plus extract_text; knowledge/service.py re-implements a stricter detector and its own docx/utf-8 dispatcher for the KB-version path (raising ValueError, with error text that even omits .docx although it is accepted), and a third static wrapper serves the legacy upload path. The legacy path accepts csv/json suffixes the KB-version path rejects, so identical files behave differently by endpoint.

## Evidence

- backend/app/services/knowledge/file_extraction.py:21 — _detect_upload_format returns any suffix/'binary' permissively; extract_text (:87-102) dispatches docx/xlsx/utf-8 and raises KnowledgeFileExtractionError
- backend/app/services/knowledge/service.py:677 — _detect_upload_text_format is a second detector (docx/markdown/text) raising ValueError('Only .txt and .md knowledge files are supported.') although the docx branch above it is accepted (:680)
- backend/app/services/knowledge/service.py:702 — _extract_kb_upload_text re-implements the docx/utf-8 dispatch of extract_text with a different error type
- backend/app/services/knowledge/service.py:398 — third wrapper KnowledgeService._extract_upload_text calls _detect_upload_format again and returns a (text, metadata) shape for upload_bytes (:355)
- backend/app/api/knowledge.py:173 — KB-version route calls upload_text_file (strict path) while api/knowledge.py:399 legacy route calls upload_bytes (permissive path)

## Impact

A format-handling bug must be fixed in up to three places; the same spreadsheet uploads to the legacy endpoint but is rejected on the KB-version endpoint; divergent exception types give the two routes different HTTP error contracts.

## Suggested fix

Keep file_extraction.py as the single owner: extend _detect_upload_format/extract_text with a strict mode (allowed_formats parameter) so upload_text_file calls extract_text(strict={docx,markdown,text}) instead of _extract_kb_upload_text; delete service.py:677-712 module helpers; have _extract_upload_text (:398) delegate the decode step to extract_text and keep only metadata assembly. Update the two api/knowledge.py call sites' exception handling in the same change.

## Notes

service.py totals 712 LOC mixing this duplication with versioning, reconciliation and mutability checks.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
