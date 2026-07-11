# Architecture Decision Records (ADRs)

> ADRs capture *why* a technology or pattern was chosen. They prevent the agent
> from proposing changes that conflict with the project's architecture.

## Rules

1. **One decision per file.** Sequential numbering: `NNNN-kebab-case-title.md`.
2. **Immutable once accepted.** If a decision is superseded, mark it `Superseded by ADR-NNNN` and create a new ADR. Do not edit the original decision.
3. **Status values:** `Proposed` → `Accepted` → `Deprecated` / `Superseded`.
4. **Anyone (human or agent) can propose an ADR**, but acceptance requires human approval (see [`../../AGENTS.md`](../../AGENTS.md) §13).
5. **Write ADRs for decisions, not features.** "Why FastAPI" yes; "Add login page" no.

## Template

```markdown
# ADR-NNNN: [Title]

- **Status:** Accepted
- **Date:** YYYY-MM-DD
- **Decider:** [who made the decision]

## Context

[What is the issue? What forces are at play? What constraints exist?]

## Decision

[What was decided? Be specific.]

## Consequences

- **Positive:** [benefits]
- **Negative:** [tradeoffs / costs]
- **Neutral:** [side effects to note]

## Related

- [Links to code, docs, other ADRs]
```

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-fastapi-for-async-backend.md) | FastAPI for the async backend | Accepted |
| [0002](0002-langgraph-manual-pipeline.md) | LangGraph topology as a manual pipeline (not compiled StateGraph) | Accepted |
| [0003](0003-postgres-pgvector.md) | PostgreSQL 16 + pgvector for relational + vector storage | Accepted |
| [0004](0004-redis-rq-not-celery.md) | Redis + RQ over Celery for background jobs | Accepted |
| [0005](0005-openrouter-llm-routing.md) | OpenRouter for multi-provider LLM routing | Accepted |
| [0006](0006-socketio-for-realtime.md) | Socket.IO over SSE for realtime communication | Accepted |
| [0007](0007-react-admin-frontend.md) | react-admin for the recruiter console SPA | Accepted |
| [0008](0008-tailwindcss-v4-css-first.md) | TailwindCSS v4 CSS-native config (no JS config) | Accepted |
| [0009](0009-event-driven-ingestion.md) | Event-driven knowledge base ingestion | Accepted |

## When to Write a New ADR

Write an ADR when you make a decision that:
- Introduces a new technology, library, or framework.
- Changes the architectural layering or dependency rules.
- Establishes a new pattern that future work must follow.
- Reverses or supersedes a previous decision.

**Do not** write an ADR for:
- Feature implementations (use `plans/`).
- Bug fixes (use `lessons/`).
- Code style preferences (use `standards/coding-style.md`).
