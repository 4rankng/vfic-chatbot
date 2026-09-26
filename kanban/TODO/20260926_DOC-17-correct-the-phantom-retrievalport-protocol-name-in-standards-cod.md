---
id: DOC-17
title: "Correct the phantom RetrievalPort protocol name in standards/coding-style.md and docs/testing.md"
severity: low
area: docs
labels: [documentation, tech-debt]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# DOC-17 — Correct the phantom RetrievalPort protocol name in standards/coding-style.md and docs/testing.md

**Severity:** low · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

**Trạng thái:** TODO

## Problem

The retrieval Protocol was renamed/typed as GraphRetrievalPort during the seam work, but two convention/test docs still cite a RetrievalPort symbol that does not exist, so the canonical DI example in the coding standard is unimplementable as written.

## Evidence

- standards/coding-style.md:22 — 'The graph layer depends on `Protocol` interfaces (`ports.py`: `ConversationPort`, `RetrievalPort`, `LeadContextPort`, `FaqBypassPort`)'; no RetrievalPort symbol exists anywhere in backend/
- backend/app/graph/ports.py:218 — GraphRetrievalPort (composed of ProjectKnowledgeQueryPort, PersonaBodyResolver, RecommendationQueryPort, …), exported at ports.py:261-266 alongside LeadContextPort and LeadGenderPort
- docs/testing.md:44 — same four-name list presented as the pattern tests must fake
- docs/HLD.md and docs/system-architecture.md contain no RetrievalPort hits — only TECH.md:87 (DOC-14), testing.md:44 (DOC-15) and coding-style.md:22 carry the stale name

## Impact

A contributor writing a fake for the retrieval dependency per the doc implements a protocol that doesn't exist, and typed fakes fail mypy against the real GraphDeps.retrieval: GraphRetrievalPort annotation (graph/types.py:123).

## Suggested fix

In standards/coding-style.md:22 replace RetrievalPort with GraphRetrievalPort (and optionally add LeadGenderPort/TurnDecisionsPort so the list matches ports.py's __all__). Keep this edit in the same commit as the DOC-14/DOC-15 port fixes so the port list is identical everywhere.

## Notes

Deliberately scoped to the two sites not covered by DOC-14/DOC-15 so the port-name fix is one grep-verified pass.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
