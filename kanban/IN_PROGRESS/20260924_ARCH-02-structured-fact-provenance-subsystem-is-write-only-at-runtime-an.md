---
id: ARCH-02
title: "Structured-fact / provenance subsystem is write-only at runtime and the canonical FAQ read path is dead"
severity: high
area: architecture
labels: [tech-debt]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-02 — Structured-fact / provenance subsystem is write-only at runtime and the canonical FAQ read path is dead

**Severity:** high · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

`models/provenance.py`'s twelve tables have writers whose only callers are themselves unreachable, and their readers are reached only through the dead `chatbot/paths.py`. The live FAQ path is the legacy chunk-based one, so the schema looks authoritative but never serves a turn.

## Evidence

- `backend/app/services/knowledge/publishing/publisher.py:69` — `publish_contract` writes the fact tables; its only caller is `backend/app/services/ingestion/recruitment_adapter.py:58`.
- `backend/app/services/ingestion/recruitment_adapter.py` — has no non-test importer (grep: only `backend/tests/test_recruitment_adapter.py:4`); `backend/app/services/ingestion/template_ingestion.py:216` is the other writer and is dead via ARCH-01.
- `backend/app/services/knowledge/tools/domain_tools.py:117,149,182,244,290` — `get_benefits`/`get_working_hours`/`get_job_requirements`/`get_job_locations`/`get_faq_entry`, whose only caller is the dead `backend/app/services/chatbot/paths.py:95,162`.
- `backend/app/models/provenance.py` — 17.7 KB defining `FaqEntry`, `JobBenefit`, `JobRequirement`, `JobLocation`, `WorkingHours`, `WorkingHoursException`, `FieldEvidence`, `ExtractionRun`, `SourceDocument`, `SourceFragment`, none of them reachable from a serving path.
- Live FAQ path: `backend/app/services/project/faq.py` → `KnowledgeChunk` rows (`repository.py:202 managed_faq_document`) → `backend/app/services/retrieval/repository.py:475,524`.

## Impact

The provenance schema, `publisher.py` and `domain_tools.py` all look authoritative but never serve a turn. Worse, this is a live correctness trap: a future reader of `models/provenance.py` will assume `FaqEntry` is the FAQ source of truth and edit the wrong table.

## Suggested fix

Decide explicitly. (a) Delete `publisher.py` + `domain_tools.py` + the fact tables and document the chunk-based FAQ as canonical, or (b) wire `domain_tools.get_faq_entry` into the FAQ pre-pass at `backend/app/graph/tools/knowledge.py:263-268` and retire `ProjectFaqService`. Leaving both is the one outcome strictly worse than either. The remaining provenance tables' deadness is inferred by transitivity through ARCH-01 [INFERENCE]; option (b) is effort L.

## Notes

Shares the ingestion cluster with ARCH-01 and the FAQ duplication pair with ARCH-17(b).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
