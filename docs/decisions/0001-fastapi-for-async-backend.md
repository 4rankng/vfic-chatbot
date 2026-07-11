# ADR-0001: FastAPI for the Async Backend

- **Status:** Accepted
- **Date:** 2026-06-26
- **Decider:** Project lead

## Context

The VFIC chatbot platform needs a backend that can:
- Handle concurrent Zalo webhook requests (chat turns) without blocking.
- Make async calls to LLM providers (MiniMax, OpenRouter, Gemini) with latency of 1–3s each.
- Serve a realtime Socket.IO connection alongside REST endpoints.
- Run on a 2 vCPU DigitalOcean droplet (limited resources).

Options considered: Django, Flask, FastAPI, Go (net/http), Node.js (Express).

## Decision

Use **FastAPI** (Python 3.12+) as the backend framework.

Key reasons:
- **Native async support.** All I/O (DB, Redis, LLM, HTTP) is `async def`. Critical for a chatbot that makes concurrent LLM calls.
- **Type safety.** Pydantic v2 integration gives request/response validation and auto-generated OpenAPI docs.
- **Dependency injection.** FastAPI's `Depends()` system composes cleanly with Protocol-based DI in the graph layer (`app/graph/ports.py`).
- **Ecosystem alignment.** LangGraph/LangChain are Python-native — staying in Python avoids a language boundary for the agent brain.
- **Performance.** Starlette/Uvicorn is among the fastest Python ASGI frameworks.

## Consequences

- **Positive:** Async-first design handles concurrent webhook + LLM calls efficiently. Pydantic v2 gives compile-time-like safety. Auto-docs reduce API documentation burden.
- **Negative:** Python's GIL means CPU-bound work must use `asyncio.to_thread` (e.g., argon2/JWT crypto). Not as fast as Go for raw throughput, but I/O-bound workload makes this acceptable.
- **Neutral:** Team must be disciplined about async (no blocking calls on the event loop — enforced by convention, see [`../../standards/coding-style.md`](../../standards/coding-style.md)).

## Related

- Backend entry point: `backend/app/main.py`
- Config: `backend/app/core/config.py`
- Async DB engine: `backend/app/core/db.py`
- [ADR-0004](0004-redis-rq-not-celery.md) — RQ workers for background jobs
- [docs/system-architecture.md](../system-architecture.md) — full runtime architecture
