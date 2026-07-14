"""Turn-level deadline + stage-budget primitive (Tech-Lead Directive §4).

The directive asks for an overall 4-second turn deadline plus stage-level budgets
with degraded fallbacks when a stage exceeds its budget. The codebase has an
existing ``state.deadline_at_epoch`` (epoch seconds, survives the FastAPI→RQ
process boundary) that bounds the FAQ-bypass lookup. This module generalizes it
into a small primitive that every stage can query.

IMPORTANT — what this primitive does NOT do (production lesson):

    The codebase deliberately removed the hard ``asyncio.wait_for`` cap on the
    agent generation call (see ``runner.py`` lines 451-457 + the retired
    ``agent_max_seconds``). Cancelling a live LLM call mid-generation produced
    excessive TIMEOUT fallbacks in prod — candidates got apologies instead of
    the real answer that was seconds away. So:

    - Retrieval, rerank, FAQ-bypass, and other CHEAP stages ARE time-boxed.
      A timed-out vector arm falls back to lexical-only; a timed-out rerank
      falls back to fused rank. These are safe: the data they produce is
      derived, and the fused list is always available as a fallback.

    - The agent LLM generation is NOT time-boxed here. The RQ job_timeout
      (>> any realistic turn) is the backstop for a genuinely hung provider
      call; the reconcile sweep recovers. This preserves the proven reliability
      behavior. Phase 2's SLO instrumentation surfaces p99 turn time so the
      decision can be revisited with data.

Construction
------------
``TurnDeadline.from_state(state, settings)`` reads the propagated
``deadline_at_epoch`` and the stage budgets from ``Settings``. When the deadline
is unset (tests / legacy), every ``expired()`` returns False and ``remaining()``
returns infinity — i.e. no time-boxing, matching pre-existing behaviour.

Stage budgets
-------------
Per-stage budgets are configurable in ``Settings``:
- ``turn_retrieval_budget_seconds`` (default 1.2) — vector + lexical, fused.
- ``turn_rerank_budget_seconds`` (default 0.6) — post-fusion rerank.

The overall ``turn_overall_deadline_seconds`` (default 10.0, mirrors
``sla_seconds``) is the source of ``deadline_at_epoch`` and is NOT re-imposed
here — it already drives the existing FAQ-bypass budget check and the SLO
rollups (Phase 2).
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnDeadline:
    """Per-turn deadline + stage budgets.

    ``overall`` is an epoch-second absolute deadline (matches
    ``BotRunState.deadline_at_epoch``). Stage budgets are *durations* in seconds,
    consumed by ``remaining(stage)`` which returns the smaller of "time left in
    this stage's budget" and "time left overall". Both ``expired(stage)`` and
    ``remaining(stage)`` are safe against an unset deadline (epoch=0 → unbounded).
    """

    overall: float  # epoch seconds, absolute; 0.0 means unset (unbounded)
    retrieval_budget: float  # seconds
    rerank_budget: float  # seconds

    @classmethod
    def from_state(cls, state, settings) -> TurnDeadline:
        """Build from ``BotRunState`` + ``Settings``.

        Reads ``state.deadline_at_epoch`` (epoch seconds, propagated across the
        FastAPI→RQ boundary) and the per-stage budgets from settings. When the
        state deadline is 0 (tests / legacy), the primitive is unbounded.
        """
        return cls(
            overall=getattr(state, "deadline_at_epoch", 0.0) or 0.0,
            retrieval_budget=getattr(settings, "turn_retrieval_budget_seconds", 1.2),
            rerank_budget=getattr(settings, "turn_rerank_budget_seconds", 0.6),
        )

    def remaining(self, stage: str) -> float:
        """Seconds remaining for ``stage``, capped by the overall deadline.

        Returns ``inf`` when the overall deadline is unset (tests / legacy).
        ``stage`` is one of: ``"overall"``, ``"retrieval"``, ``"rerank"``.
        Unknown stages fall back to the overall remaining (no per-stage cap).
        """
        if self.overall <= 0:
            return float("inf")
        overall_remaining = self.overall - time.time()
        if overall_remaining <= 0:
            return 0.0
        if stage == "retrieval":
            return min(self.retrieval_budget, overall_remaining)
        if stage == "rerank":
            return min(self.rerank_budget, overall_remaining)
        return overall_remaining

    def expired(self, stage: str) -> bool:
        """True when ``stage``'s budget is exhausted (≤ 0 seconds left)."""
        return self.remaining(stage) <= 0.0

    def budget_for(self, stage: str) -> float | None:
        """Return the per-stage budget duration (seconds), or None for overall.

        Useful for ``asyncio.wait_for(coro, timeout=deadline.budget_for(...))``.
        Returns None when the overall deadline is unset so callers can skip the
        ``wait_for`` wrapper entirely (preserving legacy unbounded behaviour).
        """
        if self.overall <= 0:
            return None
        remaining = self.remaining(stage)
        # Return a small positive floor so wait_for doesn't fire instantly on a
        # tight-but-nonzero budget; 0.0 is returned only when truly expired.
        return max(0.0, remaining)
