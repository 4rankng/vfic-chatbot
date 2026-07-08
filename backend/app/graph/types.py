"""Shared graph types: the BotRunState payload + the GraphDeps injection container."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from app.graph.llm import AgentModel, Embedder, SafetyModel
from app.graph.ports import ConversationPort, LeadContextPort, RetrievalPort

# TYPE_CHECKING avoids pulling asyncpg into the runtime import path; the
# annotation is stringified by ``from __future__ import annotations`` anyway,
# but the explicit guard keeps linters/mypy happy without the import cost.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class BotRunState:
    conversation_id: str
    version_at_start: int
    user_text: str
    user_name: str = ""
    attempt: int = 0
    reply: str = ""
    pending_message_id: int | None = None
    # Propagated ~10s turn deadline, in epoch seconds. The webhook stamps
    # ``received_at_epoch`` (time.time()) into the job so the budget survives the
    # FastAPI→RQ process boundary that time.monotonic() cannot cross; the worker
    # derives ``deadline_at_epoch = received_at_epoch + sla_seconds``. Stages check
    # ``_remaining(state)`` against it. ``0.0`` = unset → unbounded (legacy, tests).
    received_at_epoch: float = 0.0
    deadline_at_epoch: float = 0.0


class TurnOutcome(TypedDict):
    """Result of a reactive (``run_turn``) or proactive (``run_proactive_turn``) turn.

    ``outcome`` is always present (sent / suppressed / error / send_failed, with the
    proactive path prefixing ``proactive:``). ``reply`` and ``reason`` are optional
    depending on the branch taken.
    """

    outcome: str
    reply: NotRequired[str]
    reason: NotRequired[str]


@dataclass
class GraphDeps:
    db: AsyncSession  # injected at runtime; AsyncSession only for type-checking
    agent: AgentModel
    safety: SafetyModel
    embedder: Embedder
    zalo: Any
    conversation: ConversationPort
    retrieval: RetrievalPort
    # Lead-profile context for the agent prompt. None in tests that stub the turn.
    lead: LeadContextPort | None = None
    # Proactive follow-up guard: (allowed, reason). None in reactive-only tests.
    followup_allowed: Callable[[Any], Awaitable[tuple[bool, str]]] | None = None
    # Fire-and-forget candidate extraction after a SENT reply.
    # None in tests -> persistence is skipped.
    persist: Callable[[dict], None] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _speaker(msg) -> str:
    """Map ``Message.sender`` to a Vietnamese label.

    Shared by both ``runner.py`` (reactive turns) and ``proactive.py``
    (proactive nudges) to avoid drift between identical label maps.
    """
    from app.models.conversation import MessageSender

    if msg.sender == MessageSender.WORKER:
        return "Ứng viên"
    if msg.sender == MessageSender.BOT:
        return "Bot"
    if msg.sender == MessageSender.RECRUITER:
        return "Nhân viên"
    return "Hệ thống"
