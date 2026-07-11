# ADR-0005: OpenRouter for Multi-Provider LLM Routing

- **Status:** Accepted
- **Date:** 2026-06-28
- **Decider:** Project lead

## Context

The bot brain needs LLM access for:
- Agent turns (tool-calling loop) — primary model.
- Safety checks (fast filter + LLM-based safety recheck).
- Candidate extraction (structured output from conversation).
- Embeddings (knowledge chunk + query embedding, dim 3072).

The project uses multiple providers: **MiniMax** (agent, via OpenAI-compatible API) and **OpenRouter** (embeddings, default `openai/text-embedding-3-large` at dim 3072). **Gemini** is available as an alternative embedder via `EMBEDDING_PROVIDER=gemini`.

Options considered: Direct provider SDKs, OpenRouter as unified gateway, LangChain model abstractions.

## Decision

Use **OpenRouter** as the primary LLM gateway for text generation, with `langchain-openai` ChatOpenAI as the client. Use **OpenRouter** for embeddings by default (`openai/text-embedding-3-large`, dim 3072). **Gemini** (`google-genai`) is available as an alternative embedder via `EMBEDDING_PROVIDER=gemini`.

Key reasons:
- **Multi-provider routing.** OpenRouter provides a single OpenAI-compatible API that can route to MiniMax, Anthropic, OpenAI, and other models. Switching the agent model requires only an env var change (`OPENROUTER_AGENT_MODEL`).
- **Provider selection.** The application can select OpenRouter for generation
  through `LLM_DEFAULT_PROVIDER`; generation calls do not fail over at runtime.
- **Cost control.** OpenRouter's routing allows cost optimization across providers.
- **Standard client.** `langchain-openai` ChatOpenAI works with OpenRouter's OpenAI-compatible API — no custom client code.
- **Embeddings via OpenRouter by default.** `openai/text-embedding-3-large` (dim 3072) provides high-quality multilingual (Vietnamese) embeddings. Gemini (`google-genai`) is available as an alternative via `EMBEDDING_PROVIDER=gemini`.

## Consequences

- **Positive:** Model flexibility — swap agent model via env var without code changes. Single billing surface (OpenRouter). Standard OpenAI-compatible tool-calling interface.
- **Negative:** Additional network hop (app → OpenRouter → provider) adds ~100–200ms latency. OpenRouter 429s use the bounded retry and degradation path in `graph/clients.py`.
- **Neutral:** Embeddings default to OpenRouter (`openai/text-embedding-3-large`) but can be switched to Gemini via `EMBEDDING_PROVIDER=gemini`. Both generation and embeddings are configured in `app/core/config.py` with `minimax_*` / `openrouter_*` / `embedding_*` env vars.

## Related

- LLM clients: `backend/app/graph/clients.py` (`MiniMaxAgent`, `MiniMaxSafety`, embedder classes)
- Config: `backend/app/core/config.py` (`minimax_api_key`, `openrouter_api_key`, `embedding_provider`, `embedding_dim`)
- Usage tracking: `backend/app/graph/usage.py` (token + cost accounting in Redis)
- [docs/system-architecture.md](../system-architecture.md) §9 (LLM provider architecture)
- [standards/performance.md](../../standards/performance.md) — LLM concurrency control
