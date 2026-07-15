"""Turn call-budget guard (Tech-Lead Directive §2).

Directive §2: "A normal turn should use at most: zero or one routing-model
calls; zero or one embedding requests; zero or one reranker requests; zero or
one answer-generation requests."

This module enforces that bound via a small counter. Each path (C-1) calls
``assert_can_call(kind)`` before invoking an LLM/embed/rerank; exceeding the
budget raises ``BudgetExhausted`` so the runner can fall back to the
deterministic reply.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class CallKind(str, enum.Enum):
    ROUTING = "routing"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    GENERATION = "generation"


class BudgetExhausted(RuntimeError):
    """Raised when a turn tries to exceed its call budget for one kind."""


# Directive §2 per-turn caps.
_DEFAULT_BUDGETS: dict[CallKind, int] = {
    CallKind.ROUTING: 1,
    CallKind.EMBEDDING: 1,
    CallKind.RERANK: 1,
    CallKind.GENERATION: 1,
}


@dataclass
class TurnBudget:
    """Per-turn call counter. Reset by constructing a new one per turn."""

    caps: dict[CallKind, int] = field(default_factory=lambda: dict(_DEFAULT_BUDGETS))
    used: dict[CallKind, int] = field(default_factory=dict)

    def assert_can_call(self, kind: CallKind) -> None:
        """Raise BudgetExhausted if the cap for ``kind`` is already used."""
        cap = self.caps.get(kind, 1)
        used = self.used.get(kind, 0)
        if used >= cap:
            raise BudgetExhausted(f"turn budget exhausted for {kind.value}: {used}/{cap}")

    def record_call(self, kind: CallKind) -> None:
        """Increment the counter for ``kind``. Asserts the cap first."""
        self.assert_can_call(kind)
        self.used[kind] = self.used.get(kind, 0) + 1

    def remaining(self, kind: CallKind) -> int:
        """How many more calls of ``kind`` are allowed."""
        cap = self.caps.get(kind, 1)
        return max(0, cap - self.used.get(kind, 0))
