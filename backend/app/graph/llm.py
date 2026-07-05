"""LLM + embedding client boundaries (injectable for tests).

Production: MiniMax/OpenRouter chat clients plus a configured 3072-dim embedder.
Keys live server-side only. Tests inject fakes.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

# An embedder maps text -> 3072-dim vector.
Embedder = Callable[[str], Awaitable[list[float]]]


class AgentModel(Protocol):
    """A tool-calling agent: system prompt + user turn -> reply text."""

    async def agent(self, user_text: str, *, system: str, db, embedder) -> str: ...


class SafetyModel(Protocol):
    """Returns the raw M2.5 verdict text (JSON) for the candidate reply."""

    async def safety(self, candidate_reply: str) -> str: ...
