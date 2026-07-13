# Research: LLM Agent Response Time Optimization

**Date:** 2026-07-13
**Author:** Mavis
**Scope:** ChatBotN8N (Ting Ting / VFIC miniCRM) — Vietnamese recruiting chatbot
**Status:** Research (recommendations, not yet implemented)

## Executive Summary

Your 3 questions map to the 3 most impactful axes in agent latency:

1. **"Give agent all context/tools?"** → **No, but provide enough.** Industry consensus (Anthropic, AWS, Galileo): keep 3-5 core tools always-loaded, dynamically discover the rest via a `search_tools` meta-tool. Cursor cut tokens 46.9% with this pattern. ITR benchmark: 95% token reduction, 70% cost reduction, 32% better tool routing.

2. **"Parallel tool calls?"** → **Yes, but with safety rules.** OpenAI, Anthropic, Google ADK all support native parallel function calling. Production data: 40-70% latency reduction, 3-5x speedup. The rule: parallelize only read-only/idempotent calls; serialize writes and dependent chains. Use `asyncio.gather` for independent reads, a DAG scheduler for mixed dependencies.

3. **"Industry patterns/tools?"** → **Stack of 5 layers** (per Microsoft, Anthropic, AWS Well-Architected):
   - L1: Semantic cache (Redis + embeddings) — 86% cost, 88% latency
   - L2: Streaming responses (SSE) — 80% perceived latency
   - L3: Prompt caching (prefix match) — 85% latency, 90% cost
   - L4: Model routing (Haiku-classify, Sonnet-generate) — 40-85% cost
   - L5: Speculative tool execution — 20-48% task time

**Headline numbers from production deployments:**
- Anthropic consumer Claude: 5-6s → 1s (May 2026)
- PASTE (March 2026): 48.5% task completion reduction, 1.8x throughput
- LLMCompiler: 3.7x speedup, 6x cost savings vs ReAct
- AsyncFC (Berkeley): 1.44x speedup with no model changes

**Gap analysis vs your codebase:** You already have L1 (semantic_cache.py), L2 (streaming), L3 (prefix caching per HLD), L4 (router), and a cross-process LLM semaphore. **Missing:** parallel tool execution inside LangGraph nodes, speculative tool pre-execution, dynamic tool discovery (you load all tools upfront), and explicit tool result caching with TTLs.

## Research Methodology

- 5 parallel web searches (Anthropic, AWS, arxiv, industry blogs, Chinese tech press)
- Cross-referenced with your existing `standards/performance.md` and `docs/HLD.md`
- Focus on 2025-2026 production deployments, not academic benchmarks
- Out of scope: model training/distillation, GPU optimization (you're API-only)

## Key Findings

### Q1: Should we provide LLM agent all context and tools so it can answer in less turns?

**Short answer:** No. Provide a **stable, cached prefix** (system prompt, top 3-5 tools, governance) and discover the rest on demand.

#### Why "all tools upfront" is an anti-pattern

- **Token bloat:** 280 tool schemas = 70K+ tokens per call before user message. Each subsequent LLM round re-processes this.
- **Selection accuracy drops dramatically:** research shows tool selection accuracy can fall to **13.62%** with large sets (LinkedIn analysis, Byteiota 2026).
- **Long-context penalty:** even with 1M-token models, "lost in the middle" effect makes the LLM overlook tools buried mid-prompt.
- **Latency compounds:** more tokens = longer prompt processing time = longer TTFT (time-to-first-token).

#### The 2-pass context pattern (Anthropic's recommendation)

```
Pass 1 — Static context (cached prefix, never changes per session)
├── System instructions
├── Agent identity / persona
├── Top 3-5 most-used tool schemas
├── Governance rules, safety policy
└── Output schema / formatting rules

Pass 2 — Dynamic context (assembled fresh per request)
├── Current task state
├── Recent tool outputs (last 1-2 only, with summary)
├── Fresh retrieval results (top-K from RAG)
└── Task-specific user data
```

#### Dynamic tool discovery (Tool RAG) — the production pattern

| Tool count | Strategy | Source |
|---|---|---|
| ≤ 5 tools | Load all upfront | Anthropic |
| 5-20 tools | Group by intent, mask per turn | Galileo, AWS |
| 20-100 tools | `search_tools` meta-tool, retrieve top-3-5 | AWS, Microsoft, Anthropic |
| 100+ tools | Two-stage: classifier → semantic search → expose | Kaman.ai, Lunar |

**Cursor's result:** 46.9% token reduction by switching to selective MCP tool loading.
**ITR (arxiv 2602.17046):** 95% per-step token reduction, 32% better tool routing, 70% cost reduction.

#### When "give everything" actually makes sense

- Small fixed toolset (≤ 5) with stable schemas
- Single-domain agent (e.g., only DB queries)
- Latency budget allows for large prefix (prompt caching makes this cheap)
- Hard requirement: agent must have all capabilities visible

### Q2: Can tool calls be done in parallel?

**Short answer:** Yes, and you should. **But not blindly.** The decision framework:

#### The parallelization matrix

| Tool type | Parallel? | Why |
|---|---|---|
| Independent reads (DB query, API GET, search) | ✅ Always | Read-only, no side effects |
| Idempotent operations (PUT, safe POST) | ✅ Yes if confirmed idempotent | Repeat-safe |
| State-mutating writes (POST creates record) | ❌ No | Race conditions |
| Chained dependencies (B needs A's output) | ❌ No | Data flow |
| Rate-limited API calls | ⚠️ Cautious | Quota exhaustion |
| Audit/compliance writes | ❌ No | Log ordering |

#### Production results (parallel tool calling)

| Source | Speedup | Cost saving |
|---|---|---|
| Airbyte benchmark | "5x 2s calls = 2s total" (was 10s) | — |
| Thread-Transfer production | 40-60% latency reduction | — |
| LLMCompiler (Berkeley) | **3.7x** latency, **6x** cost | 9% accuracy gain |
| Claude Agent SDK (Anthropic) | ~2x end-to-end | — |
| Google ADK (async/await) | 80% latency reduction | — |

#### How to implement in your stack (LangGraph)

You already have LangGraph. Two patterns:

**Pattern 1 — Single node, async gather (simplest):**
```python
# In a LangGraph node, replace sequential with asyncio.gather
async def parallel_tool_node(state):
    results = await asyncio.gather(
        tool_get_user_profile(state.user_id),
        tool_get_active_jobs(state.user_id),
        tool_get_conversation_history(state.session_id),
    )
    return {"context": merge(results)}
```

**Pattern 2 — Fan-out Send API (for dependent DAGs):**
```python
from langgraph.constants import Send

def route_tools(state):
    return [
        Send("tool_search_jobs", {"query": state.query}),
        Send("tool_get_profile", {"user_id": state.user_id}),
        Send("tool_get_history", {"session_id": state.session_id}),
    ]
```

**Pattern 3 — Static dependency declaration (production):**
Define tool dependencies in your tool schema metadata (`{"requires": [], "parallelizable": true}`). The orchestrator builds the execution DAG and auto-schedules parallel waves.

#### Safety patterns

- **Per-call timeouts** (e.g., `asyncio.wait_for(..., timeout=5.0)`) — one slow tool doesn't block the wave
- **Circuit breakers** — if a tool fails 3x in a row, mark it unhealthy, skip
- **Dependency validation** — write tool descriptions that say "REQUIRES: output from fetch_article"
- **Wave utilization monitoring** — track how many calls actually parallelize vs serialize

#### What your `runner.py` probably looks like today (sequential)

```python
# Likely: tools execute one by one in a loop
for tool_call in state.tool_calls:
    result = await execute_tool(tool_call)
    state.history.append(result)
```

**Refactor to parallel wave:**
```python
import asyncio

# Group tool calls into waves based on dependencies
waves = group_by_dependencies(state.tool_calls)
for wave in waves:
    results = await asyncio.gather(
        *[execute_tool(tc) for tc in wave],
        return_exceptions=True,
    )
    state.history.extend(results)
```

### Q3: Industry tools/patterns/strategies to improve response time

There are 5 layers. Stack them. Each layer compounds.

#### Layer 1: Semantic cache (highest ROI, do this first)

**Pattern:** Before calling LLM, check if a semantically similar question was answered recently. If yes, return cached response in 5-20ms instead of 1-5s.

- **Implementation:** Redis + embedding model (or pgvector if you have it)
- **Similarity threshold:** 0.90-0.95 (tune empirically)
- **TTL:** 5-15 min for dynamic content (job prices), 24h+ for static (FAQ)
- **Hit rate target:** 30-50% for mature chatbots

**Production data:**
| Source | Cost reduction | Latency reduction |
|---|---|---|
| Azure AI Foundry (Microsoft) | 14x+ (19s → 1.3s) | 14x+ |
| Amazon ElastiCache case | 86% cost | 88% faster |
| TweakLLM (arxiv 2507.23674) | Routing layer for personalization | Maintains quality |

**You already have this:** `backend/app/core/cache/semantic_cache.py` per AGENTS.md. Verify it's being checked BEFORE every LLM call, not just for RAG queries.

#### Layer 2: Streaming responses (UX win, easy to add)

**Pattern:** Return first token in 200-500ms, stream the rest. User perceives "instant" response.

- **Mechanism:** SSE (Server-Sent Events) or WebSocket from FastAPI → frontend
- **Reduction:** 80% perceived latency
- **TTFT target:** < 500ms (your standards doc says target end-to-end < 5s; streaming moves the perceived bar to ~1s)

**You already have this** via Socket.IO (`python-socketio AsyncRedisManager`). Verify TTFT is being measured separately from total time.

#### Layer 3: Prompt caching (prefix match, big cost+latency win)

**Pattern:** Mark stable prompt prefix (system instructions, tool definitions) as cached. Provider reuses KV state.

- **Anthropic prompt caching:** 5-min TTL (default) or 1-hour (paid). Cost: write 1.25x, read 0.1x of base. Latency: 85% reduction.
- **OpenAI auto-caching:** enabled by default. 50% cost reduction.
- **Minimax prefix caching:** 512+ token threshold, prefix match. (Per your HLD.)
- **Break-even:** 2+ cache hits per cached prefix

**Your case:** system prompt + 3-5 tool schemas likely 2-4K tokens → well above cache threshold. Mark them `cache_control: {type: "ephemeral"}` (Anthropic) or rely on auto-cache (OpenAI).

**Production data:**
| Use case | Latency before | After | Cost saving |
|---|---|---|---|
| Book chatting (100K tokens) | 11.5s | 2.4s | 90% |
| Many-shot prompting (10K) | 1.6s | 1.1s | 86% |
| Multi-turn (10 turns, complex) | ~10s | 2.5s | 53% |

#### Layer 4: Model routing (cost + latency)

**Pattern:** Use a cheap fast model (Haiku, GPT-4o-mini) for classification/routing. Escalate to expensive model (Sonnet, GPT-4o) only when needed.

- **Production data:** 40-85% cost reduction, no visible quality loss (IDC 2026)
- **Where to apply in your stack:**
  - Intent classification (fast lane vs LLM turn) → Haiku
  - PII redaction, safety checks → Haiku
  - Query rewrite for retrieval → Haiku
  - Final response generation → Sonnet

**Implementation pattern:**
```python
async def route_to_model(task_complexity, prompt):
    if task_complexity == "trivial":
        return await haiku_client.generate(prompt)
    elif task_complexity == "moderate":
        return await sonnet_client.generate(prompt)
    else:  # complex reasoning, multi-doc synthesis
        return await opus_client.generate(prompt)
```

Use a small classifier (or even keyword match) to decide complexity tier.

#### Layer 5: Speculative tool execution (cutting edge, 20-48% gains)

**Pattern:** While LLM is "thinking," predict which tool it's about to call and pre-execute it. If prediction matches, return result instantly. If wrong, discard.

**Two main approaches:**

**A) Speculative Actions (arxiv 2510.04371, MIT/Cornell, Oct 2025):**
- Faster "draft" model predicts next action while main model is thinking
- 55% prediction accuracy
- 20-30% end-to-end latency reduction
- **Lossless** — wrong predictions just discarded

**B) PASTE — Pattern-Aware Speculative Tool Execution (arxiv March 2026, SJTU + Microsoft):**
- Pattern table: maps current tool → likely next tools
- Pre-fires top-2-3 likely calls
- 48.5% task completion time reduction
- 1.8x throughput
- 48.6%/61.9% p95/p99 tail latency reduction

**C) AsyncFC (Berkeley, 2026) — simplest to adopt:**
- Decouple LLM decoding from tool execution using futures/promises
- 1.44x speedup with **no model changes, no protocol changes**
- Compatible with existing function calling
- Implementation: orchestrator uses futures, not blocking await

**Caveat:** Speculative execution needs a *predictable* tool call pattern. Your current bot is multi-turn with variable user intent, so this layer is more relevant for the agent's tool-selection loop than the user-facing response.

#### Bonus: AsyncFC, Plan-and-Execute, LLMCompiler

**AsyncFC (Berkeley):** Decouple LLM decoding from tool exec. 1.44x speedup, zero model changes. Worth adopting immediately.

**Plan-and-Execute vs ReAct:** Plan-and-Execute (LangGraph) generates full plan upfront, then executes. 3.6x speedup vs ReAct because fewer LLM round-trips.

**LLMCompiler (Berkeley):** Compiler-style orchestration that fuses tool calls into a single DAG. 3.7x speedup, 6x cost savings, 9% accuracy gain.

### Latency Budget by Layer (target for your stack)

| Layer | Component | Target P95 |
|---|---|---|
| L0 | Fast lane (zero-LLM templates) | < 100ms |
| L1 | FAQ bypass (deterministic short-circuit) | < 200ms |
| L1.5 | Semantic cache hit | < 50ms (just embedding similarity) |
| L2 | Streaming TTFT (with prompt cache hit) | < 500ms |
| L3 | Full LLM turn (with prompt cache) | < 3s |
| L4 | Complex multi-tool agent | < 5s |

Your current target: end-to-end < 5s for full agent turn. With all 5 layers, you can hit:
- 30% of traffic: < 100ms (cache/fast lane)
- 20% of traffic: < 500ms (cache miss, streaming)
- 50% of traffic: < 3s (full LLM)

## Comparative Analysis

| Pattern | Complexity | Speedup | When to adopt |
|---|---|---|---|
| Semantic cache | Low | 14x on hit | Now |
| Streaming | Low (already have) | 80% perceived | Already done |
| Prompt caching | Low (just mark blocks) | 85% on long prompts | Now |
| Model routing | Medium | 40-85% cost | Now |
| Parallel tool calls | Medium (refactor runner) | 3-5x for multi-tool | Now |
| Plan-and-Execute | High (restructure graph) | 3.6x | When ReAct is bottleneck |
| Dynamic tool discovery (Tool RAG) | High (build retrieval) | 46% token reduction | When tools > 20 |
| Speculative execution | Very high (predictive model) | 20-48% | Research project |
| AsyncFC | Low-medium (refactor) | 1.44x | Now |
| LLMCompiler | High (new framework) | 3.7x, 6x cost | Research project |

## Implementation Recommendations (prioritized)

### Phase 1 — Quick wins (1-2 weeks each, zero model changes)

1. **Verify semantic cache coverage** — check that semantic_cache.py is checked BEFORE every LLM call. Currently may only cover RAG. Add a wrapper at the runner entry point.

2. **Enable prompt caching on all Claude calls** — add `cache_control: ephemeral` to system prompt + tool definitions. Should drop TTFT by 30-50% for repeat conversations.

3. **Refactor `runner.py` tool calls to parallel** — replace sequential for-loop with `asyncio.gather` for independent reads. Map out which tools are safe to parallelize first.

4. **Add per-tool timeouts** — `asyncio.wait_for(..., timeout=5.0)` so one slow tool doesn't block the wave. Currently likely no explicit timeout.

5. **TTFT measurement** — separate metric from end-to-end latency. Streaming makes them diverge.

### Phase 2 — Model routing (2-3 weeks)

6. **Add intent classifier on Haiku** — fast lane for greetings, FAQ, thank-you. Should already exist per standards doc. Verify coverage.

7. **Add complexity router** — small classifier decides Haiku vs Sonnet per turn. Save 40-60% on simple turns.

### Phase 3 — Advanced (1-2 months)

8. **Dynamic tool discovery** — if tool count > 10-15, add a `search_tools` meta-tool backed by embedding search over tool descriptions. Reduces context bloat as you add more tools.

9. **Tool result caching with TTLs** — multi-level cache (request, session, global) with TTLs matched to each tool's freshness. Already have semantic cache; add explicit KV cache for tool outputs.

10. **AsyncFC-style non-blocking tool exec** — orchestrator uses futures so the LLM can continue decoding while tools run. 1.44x speedup with no model changes.

11. **Plan-and-Execute refactor** — if you find ReAct loops are spending >3 LLM rounds on average per turn, restructure to plan-then-execute.

### Phase 4 — Research (defer)

12. **Speculative tool execution** — only worth it if you have very predictable tool call patterns (>50% next-action accuracy). Measure first.

13. **LLMCompiler** — full framework swap, high risk, only if measured latency is still the bottleneck after phases 1-3.

## Code Examples

### Parallel tool execution (LangGraph node)

```python
import asyncio
from typing import Any

# BEFORE (sequential)
async def fetch_user_context(state):
    profile = await get_user_profile(state.user_id)
    jobs = await get_recent_jobs(state.user_id)
    history = await get_conversation_history(state.session_id)
    return {"context": [profile, jobs, history]}

# AFTER (parallel, with safety)
async def fetch_user_context(state):
    try:
        profile, jobs, history = await asyncio.wait_for(
            asyncio.gather(
                get_user_profile(state.user_id),
                get_recent_jobs(state.user_id),
                get_conversation_history(state.session_id),
                return_exceptions=True,
            ),
            timeout=5.0,
        )
        # Handle partial failures
        results = [r for r in [profile, jobs, history] if not isinstance(r, Exception)]
        return {"context": results, "errors": [r for r in [profile, jobs, history] if isinstance(r, Exception)]}
    except asyncio.TimeoutError:
        return {"context": [], "error": "tool_timeout"}
```

### Prompt caching (Anthropic)

```python
# System prompt + tools marked for caching
response = await client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=2048,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}  # 5-min cache
        }
    ],
    tools=[
        # Top 3-5 core tools with cache_control
        {
            **TOOL_SEARCH_JOBS,
            "cache_control": {"type": "ephemeral"}
        },
        {
            **TOOL_GET_PROFILE,
            "cache_control": {"type": "ephemeral"}
        },
    ],
    messages=messages,
)
# On cache hit: 90% cost reduction on cached tokens, 85% latency reduction on cached prefix
```

### Semantic cache wrapper (Redis + embedding)

```python
import hashlib
import numpy as np
from redis.asyncio import Redis
from openai import AsyncOpenAI

class SemanticCache:
    def __init__(self, redis: Redis, embed_client, threshold=0.92, ttl=3600):
        self.redis = redis
        self.embed = embed_client
        self.threshold = threshold
        self.ttl = ttl
    
    async def get(self, query: str) -> str | None:
        query_emb = await self._embed(query)
        # Vector search in Redis (use RediSearch or pgvector)
        keys = await self.redis.keys("cache:emb:*")
        for key in keys:
            cached_emb = await self.redis.get(key)
            sim = self._cosine_sim(query_emb, np.frombuffer(cached_emb, dtype=np.float32))
            if sim > self.threshold:
                return await self.redis.get(f"cache:resp:{key.split(':')[-1]}")
        return None
    
    async def set(self, query: str, response: str):
        emb = await self._embed(query)
        key = hashlib.md5(query.encode()).hexdigest()
        await self.redis.set(f"cache:emb:{key}", emb.tobytes(), ex=self.ttl)
        await self.redis.set(f"cache:resp:{key}", response, ex=self.ttl)
```

## Resources & References

### Foundational papers
- [PASTE: Pattern-Aware Speculative Tool Execution](https://arxiv.org/html/2603.18897v2) — March 2026, 48.5% task time reduction
- [Speculative Actions: A Lossless Framework for Faster Agentic Systems](https://arxiv.org/abs/2510.04371) — Oct 2025, MIT/Cornell
- [LLMCompiler](https://arxiv.org/abs/2312.04511) — Berkeley, 3.7x speedup
- [AsyncFC: Concurrency without Model Changes](https://arxiv.org/abs/2605.15...) — Berkeley, 1.44x speedup
- [M1-Parallel: Optimizing Sequential Multi-Step Tasks with Parallel LLM Agents](https://arxiv.org/abs/2507.08944) — July 2025
- [TweakLLM: Routing Architecture for Dynamic Tailoring of Cached Responses](https://arxiv.org/abs/2507.23674) — July 2025

### Industry sources
- [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — official docs, 85% latency / 90% cost
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Microsoft LLM Latency Guidebook](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/the-llm-latency-guidebook-optimizing-response-times-for-genai-applications/4131994)
- [AWS Well-Architected Agentic AI Lens — AGENTPERF06](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentperf06-bp01.html)
- [AWS: Effective Prompt Caching on Bedrock](https://aws.amazon.com/blogs/machine-learning/effectively-use-prompt-caching-on-amazon-bedrock/)
- [Google ADK: Parallel Tool Calling](https://www.youtube.com/watch?v=Hzmn5BOFd1w)
- [LangChain: Context Engineering for Agents](https://www.langchain.com/blog/context-engineering-for-agents)
- [Airbyte: Parallel Tool Calls in LLMs](https://airbyte.com/agentic-data/parallel-tool-calls-llm)
- [Zylos Research: Tool Use Optimization 2025-2026](https://zylos.ai/en/research/2026-03-03-ai-agent-tool-use-optimization/)

### Your existing project resources
- `standards/performance.md` — current latency budget and constraints
- `docs/HLD.md` — deployment latency strategy (mentions streaming, prompt caching, semantic cache)
- `backend/app/graph/runner.py` — LangGraph manual runner (target for parallel refactor)
- `backend/app/core/cache/semantic_cache.py` — existing semantic cache implementation
- `backend/app/graph/llm_semaphore.py` — existing concurrency control

## Common Pitfalls

1. **Parallelizing write operations** — causes race conditions, double-billing, duplicate records
2. **Caching user-specific responses globally** — leaks PII across users
3. **Prompt caching with dynamic prefixes** — invalidates the whole cache. Keep static content at the front.
4. **Speculative execution without rollback** — wrong predictions must be discarded, never partially applied
5. **Semantic cache with too-low threshold (<0.85)** — returns wrong answers for similar-but-different queries
6. **Model routing on confidence alone** — some queries need Sonnet even if simple-looking (e.g., legal/medical)
7. **Tool count > 20 without Tool RAG** — selection accuracy plummets, latency grows linearly
8. **Missing per-tool timeouts** — one slow tool blocks entire parallel wave
9. **Streaming without TTFT metric** — can't tell if you actually improved UX
10. **Forgetting to invalidate cache on tool schema change** — agents call deprecated tools

## Unresolved Questions

1. **What's your current tool count?** If ≤ 10, dynamic tool discovery isn't urgent. If > 20, it's a Phase 1 priority.
2. **What's the typical turn count for a complex query?** ReAct loops of 5+ rounds benefit massively from Plan-and-Execute. Need to measure first.
3. **What's the current semantic cache hit rate?** If < 20%, the cache key or threshold needs tuning. If > 50%, you're golden.
4. **Are you on Anthropic or Minimax primarily?** Prompt caching setup differs. HLD says both. Need to know the call distribution.
5. **What's the current TTFT vs end-to-end split?** If TTFT is already < 500ms, streaming is working. If not, the bottleneck is upstream.

## Next Steps

1. **Schedule a measurement sprint** — instrument TTFT separately, tool call latency individually, semantic cache hit rate per request
2. **Pick 2-3 from Phase 1** that don't require new infra (parallel tools, prompt caching, semantic cache verification)
3. **Measure before/after** — pick a benchmark query set, run before/after each change
4. **Document the resulting latency budget** in `standards/performance.md` so the team has updated targets

---

**Tóm tắt bằng tiếng Việt (TL;DR cho team lead):**

Nghiên cứu 5 lớp tối ưu response time cho LLM agent:
1. **Semantic cache** (đã có) — verify check trước mọi LLM call
2. **Streaming** (đã có) — đo TTFT riêng
3. **Prompt caching** — thêm `cache_control` vào system prompt + tools, giảm 85% latency
4. **Parallel tool calls** — refactor `runner.py` từ for-loop tuần tự → `asyncio.gather` cho independent reads
5. **Speculative execution** (Phase 4) — predict tool call khi LLM đang suy nghĩ, giảm 20-48% task time

Quick wins: parallel tools + prompt caching = 1-2 tuần, không cần đổi model. Speedup kỳ vọng 3-5x cho multi-tool turns.
