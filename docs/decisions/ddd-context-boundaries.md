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
fails when a new violating file appears or an allowlisted file increases its
forbidden imports. Deleting an inversion passes. Owners and removal phases:

| Rule | Owner | Removal phase |
|---|---|---:|
| API -> models/core | identity, knowledge, conversation, recruitment slices | 3–6 |
| Transport schemas -> models/core | owning backend context | 3–6 |
| Services -> graph | shared contracts + owning context | 2–6 |
| Services -> workers | job-port owner | 4–5 |
| Frontend `lib/vfic` <-> product features | owning frontend slice | 7–8 |

The allowlist is a ceiling, not a target. No phase may expand it.

## Runtime Lifetime Contract

Composition does not imply one lifetime. Process/event-loop clients and locks,
request/job sessions, per-turn adapters, transaction-scoped repositories, and
single-operation sessions remain distinct. Durable commit, event, audit, enqueue,
and provider-I/O boundaries must be characterized before movement.

## Consequences

- Each phase uses a strangler cut: characterize, add a port/use case, wrap the
  current implementation, switch named callers, verify, remove the old seam.
- Stable RQ callable paths and N/N-1 decoders remain durable contracts until an
  operational drain proves serialized callers are gone.
- Multi-tenancy is deliberately absent. The deferred design must consume these
  boundaries later rather than introducing tenant abstractions now.
