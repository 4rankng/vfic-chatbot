---
type: wiki
title: "TingHire quickstart"
description: "Task-routing entry point that maps user intent to the right wiki page (deploy, debug bot turn, RAG, lead pipeline, RBAC, frontend)."
tags: [quickstart, routing, index, onboarding]
sources:
  - id: openwiki-source-8037e2358a2c4f9b2c722a11
    resource: repo://AGENTS.md
  - id: openwiki-source-8b373631ac8c5d9bdb7cf697
    resource: repo://backend/app/identity/domain/role.py
  - id: openwiki-source-83138473302f47a1c6ad79fa
    resource: repo://backend/app/models/user.py
  - id: openwiki-source-7bf716cadda110352bd12063
    resource: repo://backend/app/prompts/candidate_extraction.py
  - id: openwiki-source-e4225e8ec527cd572e3a6fe0
    resource: repo://backend/app/recruitment/domain/statuses.py
  - id: openwiki-source-097e0c9cfb011c3e4a091e1a
    resource: repo://docs/codebase-summary.md
generated: { by: "opencode", at: "2026-09-21T12:36:52.415Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T12:36:52.415Z
---

# TingHire quickstart

This page routes your intent to the right wiki page. Find your task below and
follow the link.

## "I want to understand the system"

| Question | Page |
|---|---|
| What is TingHire and what does it do? | [System overview](architecture/system-overview.md) |
| How is it deployed? | [Blue/green deployment](architecture/deployment.md) |
| What are the config knobs? | [Configuration](operations/configuration.md) |
| How do I set up the dev environment? | `docs/codebase-summary.md` (source of truth) |

## "I want to debug something"

| Symptom | Page |
|---|---|
| Bot turn is stuck or slow | [Bot-turn pipeline](bot/pipeline.md) → [Reconcile worker](workers/pipeline-and-recovery.md) |
| Bot reply is wrong or unsafe | [Safety filter chain](bot/safety-and-routing.md) → [Decision trace](bot/decision-trace.md) |
| Candidate didn't get a reply | [Reconcile worker](workers/pipeline-and-recovery.md) → [Conversation lifecycle](messaging/conversation-lifecycle.md) |
| Realtime push not reaching the console | [Realtime push (Socket.IO)](messaging/realtime-socketio.md) |
| Knowledge/RAG returning wrong results | [RAG retrieval](knowledge/rag.md) → [Knowledge ingestion](knowledge/ingestion.md) |
| LLM provider 429s or timeouts | [Configuration](operations/configuration.md) (concurrency limits) → [Observability](operations/observability.md) |
| Worker OOM or crash | [RQ queues and recovery](workers/pipeline-and-recovery.md) |

## "I want to change something"

| Task | Page |
|---|---|
| Add a new LLM provider | [Configuration](operations/configuration.md) → `graph/clients.py` |
| Change the bot prompt | `graph/prompts.py` (source of truth) |
| Add a new channel adapter | [Zalo adapters](channels/zalo-adapters.md) → `channels/registry.py` |
| Modify lead stages or scoring | [Lead lifecycle](recruitment/lead-lifecycle.md) → [Recommendation](recruitment/recommendation.md) |
| Change follow-up cadence | [Proactive follow-up](recruitment/proactive-followup.md) |
| Add a new API endpoint | `docs/code-standards.md` (conventions) → [System overview](architecture/system-overview.md) |
| Modify the frontend console | [Frontend architecture](frontend/recruitment-console.md) |
| Change RBAC rules | [JWT auth and RBAC](access/rbac-and-capabilities.md) |
| Add/modify integration credentials | [Integration credentials](access/integrations-credentials.md) |

## "I want to test something"

| Task | Page |
|---|---|
| Run the backend unit suite | [Testing strategy](operations/testing-strategy.md) |
| Run the integration lane (requires PostgreSQL) | [Testing strategy](operations/testing-strategy.md) |
| Run E2E tests (Playwright) | [Testing strategy](operations/testing-strategy.md) |
| Run the RAG benchmark | [Testing strategy](operations/testing-strategy.md) |
| Check observability endpoints | [Observability](operations/observability.md) |

## "I want to deploy"

| Task | Page |
|---|---|
| Deploy to production | [Blue/green deployment](architecture/deployment.md) |
| Rollback a bad deploy | [Blue/green deployment](architecture/deployment.md) (make rollback) |
| Check deployment health | [Observability](operations/observability.md) (GET /health, /metrics, /health/queue) |

## Key source paths

| Area | Path |
|---|---|
| API routes | `backend/app/api/` |
| Business logic | `backend/app/services/` |
| Bot graph pipeline | `backend/app/graph/` |
| Workers | `backend/app/workers/` |
| Models | `backend/app/models/` |
| Frontend components | `frontend/src/components/atomic-crm/` |
| Shared types | `backend/app/schemas/`, `backend/app/shared/` |
| Migrations | `backend/alembic/versions/` |
| Tests | `backend/tests/`, `frontend/src/**/*.test.*` |

## Vietnamese domain terms

| Term | Meaning |
|---|---|
| *Quản trị* | Admin role |
| *Tuyển dụng* | Recruiter role (default) |
| *đồng* (VND) | Vietnamese currency |
| *Mới / Đang liên hệ / Đã đăng ký / Bỏ qua* | Lead stages (NEW / CONTACTING / REGISTERED / SKIPPED) |
| *lái xe / công nhân / kho / bán hàng / bảo vệ* | Common candidate desired_job categories |
