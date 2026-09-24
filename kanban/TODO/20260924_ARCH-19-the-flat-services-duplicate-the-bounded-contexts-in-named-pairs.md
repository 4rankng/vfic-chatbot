---
id: ARCH-19
title: "The flat services duplicate the bounded contexts in named pairs"
severity: medium
area: architecture
labels: [tech-debt]
effort: L
status: todo
column: TODO
opened: 2026-09-24
---

# ARCH-19 — The flat services duplicate the bounded contexts in named pairs

**Severity:** medium · **Area:** architecture · **Effort:** L · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

The flat `app/services/` layer and the bounded contexts implement the same concepts twice, so a fix must be applied in two places and only one copy is exercised in production.

## Evidence

- `backend/app/services/knowledge/service.py` (705 LOC) versus `backend/app/services/knowledge_base_service.py` (453 LOC) — both query `Project`/`KnowledgeBase`/`KnowledgeDocument` and both are called from the same router, `backend/app/api/knowledge_bases.py:25-26,134-137`, which selects between them on a `project_id is not None` branch.
- `backend/app/services/knowledge/text_ingestion.py:32,41,58,63` — two text-stats functions over two near-identical normalizers whose only difference is that `normalize_kb_scalar` strips `\r` before the shared pipeline.
- `backend/app/services/webhook.py::ZaloWebhookService` (entered via `backend/app/composition/conversation_messaging.py:101-114`) versus `backend/app/channels/ingress.py::ChannelIngressService` (via `backend/app/api/webhooks.py:265-268`) — two different dedup/ensure/record orderings for the same "inbound text" concept.
- The FAQ pair (`backend/app/services/project/faq.py` chunk-based vs `models/provenance.py` `FaqEntry`) and the grounding pair (`graph/grounding.py` vs the `_ground_*` family in `graph/clients.py`) are ticketed separately as ARCH-02 and ARCH-05.
- Deliberately **not** duplication: the legacy `KnowledgeDocument`/`KBVersion` write model versus category revisions is guarded by `_require_legacy_mutation_allowed` (`backend/app/services/knowledge/service.py:652`) and is correct in-flight migration work.

## Impact

A change to inbound dedup/ensure ordering or to knowledge text normalisation has to be made twice, and the two copies can silently diverge — the Messenger and Zalo inbound paths already order their steps differently.

## Suggested fix

Merge `KnowledgeBaseService` into `services/knowledge/` as `knowledge/base_service.py` and collapse the two normalizers into one. Converge Messenger onto `ZaloWebhookService`'s dedup/ensure/record ordering, or vice versa — pick one shared step list rather than two. Do this only after ARCH-02 decides which FAQ/fact path is canonical.

## Notes

Split from a merged ticket. The import-edge half is ARCH-17. Sequence after ARCH-02.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
