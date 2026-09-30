"""LLM + embedding client boundaries (injectable for tests).

Production: MiniMax/OpenRouter chat clients plus a configured 3072-dim embedder.
Keys live server-side only. Tests inject fakes.
"""

from __future__ import annotations

from typing import AsyncContextManager, Awaitable, Callable, Protocol

# An embedder maps text -> 3072-dim vector.
Embedder = Callable[[str], Awaitable[list[float]]]

# Factory yielding a fresh GraphRetrievalPort on its own DB session (parallel tools).
MakeRetrieval = Callable[[], AsyncContextManager]


class DecisionTraceSink(Protocol):
    def record_decision(self, code: str, summary_code: str) -> None: ...

    def record_tool_selection(self, name: str, *, selected_by: str) -> None: ...

    def record_model_turn(
        self,
        *,
        phase: str,
        provider: str,
        model: str,
        reasoning: str | None,
        tool_names: list[str] | None = None,
    ) -> None: ...


class AgentModel(Protocol):
    """A tool-calling agent: system prompt + user turn -> reply text.

    ``allowed_tools`` (optional) restricts the tools bound for this turn — the router's
    hard gate. ``None``/empty binds the full toolset (the pre-routing default).
    ``make_retrieval`` (optional) enables parallel tool dispatch: when provided and
    multiple tool calls arrive in one LLM response, each runs on its own session.
    ``required_tool`` forces the first tool round to establish an authority source;
    ``required_tool_args`` replaces model-supplied arguments for that tool.
    ``on_delta`` (optional) receives answer text as it is streamed, enabling
    progressive delivery; without it the call is a single blocking ``ainvoke``.
    ``on_evidence`` (optional) receives the accumulated tool results after each
    tool dispatch, so a streamed bubble can be grounded against the evidence the
    model had actually seen at that point.
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
        required_tool: str | None = None,
        required_tool_args: dict | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        on_evidence: Callable[[list[str]], Awaitable[None]] | None = None,
        trace_sink: DecisionTraceSink | None = None,
    ) -> str: ...
