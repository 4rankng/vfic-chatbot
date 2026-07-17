"""LLM + embedding client boundaries (injectable for tests).

Production: MiniMax/OpenRouter chat clients plus a configured 3072-dim embedder.
Keys live server-side only. Tests inject fakes.
"""

from __future__ import annotations

from typing import AsyncContextManager, Awaitable, Callable, Protocol

# An embedder maps text -> 3072-dim vector.
Embedder = Callable[[str], Awaitable[list[float]]]

# Factory yielding a fresh RetrievalPort on its own DB session (parallel tools).
MakeRetrieval = Callable[[], AsyncContextManager]


class AgentModel(Protocol):
    """A tool-calling agent: system prompt + user turn -> reply text.

    ``allowed_tools`` (optional) restricts the tools bound for this turn — the router's
    hard gate. ``None``/empty binds the full toolset (the pre-routing default).
    ``make_retrieval`` (optional) enables parallel tool dispatch: when provided and
    multiple tool calls arrive in one LLM response, each runs on its own session.
    """

    async def agent(
        self,
        user_text: str,
        *,
        system: str,
        retrieval,
        embedder,
        allowed_tools: tuple[str, ...] | None = None,
        resolved_tool_registry: frozenset[str] | None = None,
        use_fast: bool = False,
        make_retrieval: MakeRetrieval | None = None,
        lookup_query: str | None = None,
        metrics: dict | None = None,
    ) -> str: ...

    async def direct(self, user_text: str, *, system: str, metrics: dict | None = None) -> str: ...


class SafetyModel(Protocol):
    """Returns the raw M2.5 verdict text (JSON) for the candidate reply."""

    async def safety(self, candidate_reply: str) -> str: ...
