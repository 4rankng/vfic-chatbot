"""Typed ports (dependency-injection interfaces) for the graph layer.

The agent brain must not import concrete service classes — that coupling is what
made the layer un-testable in isolation and created the latent graph ↔ services
import edge. Instead the brain depends on these Protocols; the composition root
(:func:`app.graph.factories.build_deps`) constructs the concrete services and
injects them via :class:`~app.graph.types.GraphDeps`.

Ports are intentionally loose-typed (``Any`` for domain objects): they describe
*what the brain calls*, not the full service surface, so the concrete service can
evolve without dragging the contract along.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SendOutcome:
    """Graph-local send result (mirrors the service-layer ``SendResult`` shape).

    The proactive turn constructs synthetic outcomes for non-send paths (the agent
    decided not to send, safety blocked, generation threw). Defining the shape here
    keeps the graph layer from importing the Zalo service module. Downstream
    persistence reads only ``ok`` / ``msg_id`` / ``error``, so this satisfies the
    service contract structurally.
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class FaqBypassResult:
    """A high-confidence FAQ answer ready to send without an LLM turn.

    The deterministic FAQ-bypass cascade returns this when it is confident;
    ``None`` means "abstain — route to the agent". ``answer`` is the only field
    the runner sends; the rest are carried for the decision log.
    """

    answer: str
    faq_id: str | None = None
    tier: str = ""  # exact / hybrid
    score: float = 0.0
    reason: str = ""
    latency_ms: float = 0.0


class ConversationStatePort(Protocol):
    async def record_proactive_outcome(
        self, conv: Any, *, message: str, result: Any, lock_owner: Any = None
    ) -> Any: ...

    async def release_lock(self, conv: Any, lock_owner: Any = None) -> None: ...


class ConversationPort(Protocol):
    """Subset of the conversation service surface the brain depends on."""

    state: ConversationStatePort

    async def get(self, conversation_id: Any) -> Any: ...

    async def last_messages(self, conv: Any, *, limit: int) -> list[Any]: ...

    async def record_bot_pending(self, conv: Any) -> Any: ...

    async def record_bot_outcome(
        self,
        conv: Any,
        *,
        version_at_start: int,
        reply: str,
        started_at: Any,
        sent: bool,
        pending_message_id: int | None,
        external_error: str | None = None,
        zalo_message_id: str | None = None,
        stage_timings: dict | None = None,
        lock_owner: Any = None,
    ) -> None: ...

    async def recheck_ownership(
        self, conv: Any, version_at_start: int, lock_owner: Any = None
    ) -> bool: ...

    async def claim_send(
        self,
        conv: Any,
        *,
        version_at_start: int,
        lock_owner: Any,
        pending_message_id: int | None,
        reply: str,
    ) -> bool: ...

    async def acquire_lock(self, conv_id: Any) -> Any: ...


class LeadContextPort(Protocol):
    """Lead-profile context the brain injects into the agent prompt.

    ``context`` does one DB fetch and returns both the profile text and the
    next lead-collection question (``""`` each on miss); ``profile_text`` is the
    single-fetch flavor used by the proactive turn. ``instruction`` / ``ensure``
    are pure prompt-assembly post-processors.
    """

    async def profile_text(self, chat_id: str) -> str: ...

    async def context(
        self, chat_id: str, current_user_text: str, recent_messages: list[Any]
    ) -> tuple[str, str]: ...

    def instruction(self, question: str) -> str: ...

    def ensure(self, reply: str, question: str) -> str: ...


class RetrievalPort(Protocol):
    """Retrieval repository surface the agent tools + prompt assembly depend on."""

    async def active_persona_body(self) -> str | None: ...

    async def active_projects_with_card(self) -> list[Any]: ...

    async def match_memories(self, embedding: str, top_k: int, filters_json: str) -> list[Any]: ...

    async def project_id_by_slug(
        self, slug: str, *, active_only: bool = False
    ) -> Any: ...

    async def match_faq(
        self, embedding: str, *, top_k: int = 3, project_ids: list[str] | None = None
    ) -> list[Any]: ...

    async def match_documents(
        self,
        embedding: str,
        top_k: int,
        filters_json: str,
        *,
        project_ids: list[str] | None = None,
        query_text: str = "",
    ) -> list[Any]: ...

    async def list_active_projects(self) -> list[Any]: ...

    async def search_bus_timetable(self, company: str, question: str, limit: int) -> list[Any]: ...

    async def job_features_for_project(self, project_id: Any) -> list[Any]: ...

    async def match_jobs_for_lead(
        self, chat_id: str, *, top_k: int = 5, province: str | None = None
    ) -> list[Any]: ...


class FaqBypassPort(Protocol):
    """Deterministic, non-LLM FAQ short-circuit that runs before the agent node.

    Returns a ready-to-send :class:`FaqBypassResult` on a high-confidence hit, or
    ``None`` to abstain (the agent then handles the turn as usual). Backed by
    :class:`app.graph.factories._FaqBypassAdapter`; ``None`` in graph unit tests.
    """

    async def try_answer(self, user_text: str) -> FaqBypassResult | None: ...


__all__ = [
    "SendOutcome",
    "FaqBypassResult",
    "FaqBypassPort",
    "ConversationPort",
    "ConversationStatePort",
    "LeadContextPort",
    "RetrievalPort",
]
