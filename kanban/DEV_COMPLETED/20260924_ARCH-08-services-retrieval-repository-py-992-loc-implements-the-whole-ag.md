---
id: ARCH-08
title: "`services/retrieval/repository.py` (992 LOC) implements the whole agent read surface and self-constructs its collaborators"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-08 — `services/retrieval/repository.py` (992 LOC) implements the whole agent read surface and self-constructs its collaborators

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

One class owns memory match, document hybrid retrieval, FAQ, the project catalog, the persona body, the bus timetable and job/income reads. Four of its methods construct a `RecommendationRepository` — and one a `LeadRepository` — inline instead of receiving them, so the port the graph injects silently instantiates two other services per call.

## Evidence

- `backend/app/services/retrieval/repository.py:161` — memory match; `:201,257,316,405,442` — document hybrid retrieval; `:475,524` — FAQ; `:606,621,643,705,718` — project catalog; `:668` — persona body; `:589,741` — bus timetable; `:899,920,927,960` — job features, income summary, job recommendations, active jobs.
- `backend/app/services/retrieval/repository.py:922,933,963,982` — `from app.services.recommendation import RecommendationRepository` inside method bodies; `:935` — `LeadRepository` likewise.
- `backend/app/graph/factories.py:856` — the graph injects this as its read-only retrieval port, so each of those calls instantiates a recommendation repository and a lead repository.
- `backend/app/project_knowledge/application/retrieval.py:9-25` — `ProjectKnowledgeQueryPort` declares `job_features_for_project` and `income_summary_for_active_projects`, recruitment concerns absorbed by a project/knowledge-owned port because of this coupling.

## Impact

The read-only retrieval port the graph injects reaches into two other services per call, and a project/knowledge-owned port now declares recruitment concerns — the seam is in the wrong place, which is why the port had to absorb them.

## Suggested fix

Split into `retrieval/document_repository.py` (`:161-473`), `retrieval/faq_repository.py` (`:475-583`), `retrieval/catalog_repository.py` (`:606-757`) and `retrieval/timetable_repository.py` (`:741-897`), and inject `RecommendationQueryPort` (which already exists at `recruitment/application/ports.py` and is already imported by `graph/ports.py:20`) instead of importing `RecommendationRepository`. That also lets `ProjectKnowledgeQueryPort` shed its recruitment methods.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
