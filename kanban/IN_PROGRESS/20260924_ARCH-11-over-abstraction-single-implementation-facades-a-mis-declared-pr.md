---
id: ARCH-11
title: "Over-abstraction: single-implementation facades, a mis-declared Protocol and a test double in production code"
severity: medium
area: architecture
labels: [tech-debt, testing]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-11 — Over-abstraction: single-implementation facades, a mis-declared Protocol and a test double in production code

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** tech-debt, testing

**Trạng thái:** TODO

## Problem

Several Protocols and facades have exactly one implementation and no behaviour of their own, one facade is wired two different ways depending on the caller, a Protocol is used as a dataclass, and a conformance-suite test double ships in `app/`.

## Evidence

- `backend/app/project_knowledge/application/categories.py:54` — `CategoryUseCases`, seven methods each a bare `return await self._port.<same name>(...)`, typed `object`/`Any`; one implementation (`SqlAlchemyCategoryAdapter`); consumers at `backend/app/api/projects.py:237,251,271,286,327,351,366,384`.
- `backend/app/services/knowledge/external_source_sync/__init__.py:355-357` — constructs `CategoryUseCases(KnowledgeCategoryService(db))` directly, bypassing `build_category_use_cases` (`backend/app/composition/project_knowledge.py:50`), so the same facade has two different adapters.
- `backend/app/project_knowledge/application/ingestion.py:26` — `KnowledgeIngestionUseCases`, two pure-delegation methods, one implementation; `backend/app/project_knowledge/application/cache.py:8` — `ProjectKnowledgeCacheRepairPort`, one method, one implementation.
- `backend/app/capabilities/contracts.py:9` — `CapabilityAdapter` declared as a Protocol whose only "implementation" is the frozen dataclass `RecruitmentAdapterDescriptor` (`backend/app/capabilities/recruitment/adapter.py:6`); `adapter_descriptors` is populated at `registry.py:97` and never consumed.
- `backend/app/channels/accounts.py:44` — `_StaticChannelAccountResolver`, docstring: "This double lets the conformance suite exercise active/inactive behavior without a database".

## Impact

Indirection with no behaviour to hide, a facade that resolves to different adapters depending on the caller, and a test double shipped in production code — all of which make a reader look for behaviour that is not there.

## Suggested fix

Delete `CategoryUseCases` and `KnowledgeIngestionUseCases` (call the adapters directly from the composition root, as `graph/factories.py` already does) and fix `external_source_sync/__init__.py:355` to go through `build_category_use_cases` in the same change; convert `CapabilityAdapter` from a Protocol to the dataclass it actually is. The rule to apply: a Protocol earns its place when a fake exists that changes behaviour under test, or two implementations are planned in the same change — contrast `graph/ports.py` and `conversation_messaging/application/outbound_recovery.py::OutboundRecoveryPort`, which have real fakes.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
