# ADR-0002: LangGraph Topology as a Manual Pipeline (Not Compiled StateGraph)

- **Status:** Accepted
- **Date:** 2026-06-28
- **Decider:** Project lead

## Context

The bot brain needs a structured pipeline: load state → fast lane → FAQ bypass → agent → safety filter → pre-send guard → send → record outcome. This topology maps to LangGraph's `StateGraph` concept.

The project depends on `langgraph>=0.2` and `langchain-core>=0.3`, and uses `langchain-openai` ChatOpenAI as the LLM client and `langchain-core.messages` (SystemMessage, HumanMessage, ToolMessage) for the agent loop.

## Decision

Implement the graph topology as a **manual pipeline** in `backend/app/graph/runner.py:run_turn()` rather than a compiled LangGraph `StateGraph`.

The pipeline mirrors the LangGraph topology 1:1 (per `runner.py` docstring), with explicit conditional branching for safety checks and retry logic.

## Consequences

- **Positive:** Full control over the execution flow — no black-box compiled graph behavior. Easier to debug (every step is a traceable function call). No dependency on LangGraph's compilation internals, which were evolving rapidly.
- **Negative:** Must manually implement retry, error recovery, and state transitions that a compiled StateGraph would handle. More boilerplate.
- **Neutral:** Still uses `langchain-core` message types and `langchain-openai` ChatOpenAI for LLM calls — so the LLM client layer is standard.

## Related

- Pipeline entry: `backend/app/graph/runner.py` (`run_turn()`)
- Proactive pipeline: `backend/app/graph/proactive.py` (`run_proactive_turn()`)
- Composition root: `backend/app/graph/factories.py` (`build_deps()`)
- Protocol interfaces: `backend/app/graph/ports.py`
- [docs/system-architecture.md](../system-architecture.md) §3 (Bot-turn pipeline topology)
- [docs/troubleshooting/chatbot-response-path.html](../troubleshooting/chatbot-response-path.html) — debugging map
