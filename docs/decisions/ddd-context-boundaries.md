# DDD Context and Layer Boundaries

## Status

Accepted for incremental single-tenant migration on 2026-07-22. This decision
describes dependency ownership; it does not change product behavior, public
contracts, database schema, or deployment topology.

## Context

The modular monolith already has useful seams—graph Protocols, channel adapters,
domain-oriented service packages, and frontend feature folders—but dependency
direction is inconsistent. API and transport schemas import persistence directly;
services import graph and worker implementations; frontend adapters and product
features import each other. A big-bang rewrite would put production behavior at
risk, so current inversions are frozen and removed slice by slice.

## Backend Context Ownership

| Context | Owns | Does not own |
|---|---|---|
| Identity and access | authentication use cases, role/capability policy | FastAPI, JWT/crypto implementation |
| Runtime authority and installation | lifecycle, readiness, public projection policy | database/cache adapters |
| Project and knowledge | projects, knowledge modes, ingestion, retrieval, derived Job writes | LLM/embed/RQ implementations |
| Conversation and messaging | inbound commands, ownership, message/outbox state | webhook/provider/realtime transports |
| Channels and outbound | neutral delivery contract and provider selection | conversation policy, graph policy |
| Recruitment | leads, personas, recommendations, follow-ups, Job queries | derived Job writes, LLM provider objects |
| Agent runtime | bot-turn orchestration, reply/safety/grounding policy | concrete services and provider credentials |
| Reporting | read models and projections | write-side business decisions |

### Production package map

| Production surface | Owning layer/context |
|---|---|
| `app/api`, `app/realtime` | inbound HTTP/WebSocket adapters |
| `app/identity`, `app/access` | identity/access domain, application ports/use cases, and infrastructure adapters |
| `app/installation/domain` | framework-free single-installation projection policy |
| `app/integrations/facebook_oauth` | Facebook OAuth domain/application boundary and Redis/encryption adapter |
| `app/project_knowledge` | project/knowledge domain policies, application job/provider/query ports, and SQL/cache adapters |
| `app/composition` | cross-context construction for RQ and current graph-client adapters |
| `app/schemas` | transport DTOs; migrated with their owning API slice |
| `app/graph` | agent-runtime application/domain policy; `factories.py` is its composition root |
| `app/services/installation` | runtime authority and installation |
| `app/services/project`, `knowledge`, `ingestion`, `retrieval` | project and knowledge |
| `app/services/conversation`, `chatbot`, `outbox_service.py`, channel services | conversation, messaging, channels/outbound |
| `app/services/lead`, `personas`, `proactive`, `recommendation` | recruitment |
| `app/services/dashboard`, performance/SLO services | reporting projections |
| `app/workers` | RQ inbound adapters; stable callable paths are durable contracts |
| `app/models`, `app/core` | persistence and technical infrastructure adapters |

Frontend ownership is: `conversations` plus conversation-facing `contacts` and
`cases` (conversation slice); `knowledge`, `knowledge-base`, and `projects`
(project/knowledge slice); `personas`, `dashboard`, `capabilities/recruitment`,
and `workflows` (recruitment/reporting slice); `login`, `profiles`, `users`,
`installation`, `integrations`, and `settings` (identity/installation slice).
`providers`, `root`, `layout`, `kit`, `hooks`, `misc`, and `performance` are
composition, adapter, presentation, or cross-slice read-only surfaces.

## Dependency Rules

```text
API / workers / realtime / providers -> application use cases -> domain
infrastructure adapters implement inward ports
composition roots are the only concrete wiring location
```

- Domain modules import no FastAPI, Pydantic transport schema, SQLAlchemy,
  Redis, RQ, Socket.IO, provider SDK, React, react-admin, or browser API.
- Application modules may depend on domain and Protocol/value contracts only.
- Adapters may depend inward; inward layers never import adapters.
- Cross-context calls use an owning context's application entry point or port,
  never another context's repository/model internals.
- SQLAlchemy models remain persistence mirrors during this migration.

Frontend domain-rich features follow `presentation -> application -> domain`,
with infrastructure implementing application ports. Declarative CRUD and
presentation-only features stay thin; four folders are not a goal by themselves.

## Enforced Legacy Baseline

`backend/tests/test_architecture_boundaries.py` scans Python and TypeScript and
fails when a new forbidden edge appears. Deleting an inversion passes. Owners
and removal phases:

| Rule | Owner | Removal phase |
|---|---|---:|
| API -> models/core | identity, knowledge, conversation, recruitment slices | 3–6 |
| Transport schemas -> models/core | owning backend context | 3–6 |
| Services -> graph | shared contracts + owning context | 2–6 |
| Services -> workers | job-port owner | 4–5 |
| Frontend `lib/vfic` <-> product features | owning frontend slice | 7–8 |

The allowlist is a ceiling, not a target. No phase may expand it.

The scanner freezes exact normalized importer-to-symbol edges for Python and
importer-to-module edges for TypeScript. It resolves relative paths and covers
static, side-effect, dynamic, and CommonJS TypeScript imports. Synthetic tests
exercise these forms so an allowlisted file cannot swap or add a forbidden
symbol without an explicit baseline review. Dynamic imports with literal module
names are covered, including aliases, comments, escapes, and Python relative
package resolution; computed module names are outside this static guard and
remain subject to code review.

## Frozen Runtime Contracts

The executable inventory in `backend/tests/test_runtime_surface_inventory.py`
is the detailed source of truth: 172 HTTP endpoints and 41 named queue/outbox/
provider call records (117 under the broad detector) are classified and hashed.
Any route or dispatch change requires an explicit snapshot review.

- Queues: `webhook_high`, `persistence_low`, `ingest`, and `followup`; RQ module
  paths and payload decoders remain stable until Phase 9 drain evidence.
- Realtime rooms: `user:{id}`, `conv:{conversation_id}`, and `lead:{lead_id}`.
  Public client events include `join/leave conversation`, `join/leave lead`,
  `message.created`, and `lead.updated`.
- `GraphDeps` fields: `db`, `agent`, `embedder`, `zalo`, `conversation`,
  `retrieval`, `reply_policy`, `safety`, `lead`, `make_retrieval`, `faq_bypass`,
  `followup_allowed`, `persist`, `enrich_oa_profile`, `runtime_policy`, and
  `direct_context`. Protocols live in `app/graph/ports.py`.
- Frontend resource names are frozen by
  `capabilities/static-recruitment-runtime.test.ts`; provider aliases remain in
  `providers/rest/dataProvider.ts` until their owning feature migration.
- High-risk characterization suites cover auth/capability order, webhook-to-RQ
  dispatch, outbox send claims, knowledge activation/retrieval, takeover,
  proactive turns, and frontend runtime reset/realtime subscription lifetime.

The pre-migration local baseline is 1,854 passing backend non-integration tests
(23 skipped) and 494 passing frontend unit tests. Latency-sensitive production
flows are webhook acknowledgement, queue wait, cached response, model/provider
call, full answer, and provider send. Existing release targets remain authoritative:
full-answer p95 below 4 seconds for the release gate and operational bot-turn p95
below 30 seconds with a 60-second hard cap; Phase 1 changes no thresholds.

## Runtime Lifetime Contract

Composition does not imply one lifetime. Process/event-loop clients and locks,
request/job sessions, per-turn adapters, transaction-scoped repositories, and
single-operation sessions remain distinct. Durable commit, event, audit, enqueue,
and provider-I/O boundaries must be characterized before movement.

Project/knowledge scheduling preserves five operation-specific contracts behind
one application facade: document ingest is fire-and-forget; version and category
work require stable receipts; RAG and single-page source sync may return no
receipt and retain their existing ambiguity handling. The RQ adapter continues
to call the established worker facades from the composition root, so serialized callable paths and queue
payloads are unchanged. Three direct service-owned enqueue calls disappeared
from the broad static inventory; this is a boundary deletion, not a runtime
surface removal.

Category activation, project authority cutover/rollback, and single-page publish
continue to commit their database authority before cache repair. Cache repair is
best-effort and has no durable outbox in this phase. That bounded convergence gap
is retained deliberately so a structural extraction does not change failure
semantics or require a schema migration.

## Consequences

- Each phase uses a strangler cut: characterize, add a port/use case, wrap the
  current implementation, switch named callers, verify, remove the old seam.
- Stable RQ callable paths and N/N-1 decoders remain durable contracts until an
  operational drain proves serialized callers are gone.
- Multi-tenancy is deliberately absent and deferred until 2026-10-22. It
  requires a new explicit decision, and the deferred design must consume these
  boundaries later rather than introducing tenant abstractions now.
