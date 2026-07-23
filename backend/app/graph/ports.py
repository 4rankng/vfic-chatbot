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

from app.conversation_messaging.application.ports import DeliveryResultPort
from app.project_knowledge.application.retrieval import ProjectKnowledgeQueryPort
from app.recruitment.application.ports import (
    LeadContextQueryPort,
    PersonaBodyResolver,
    RecommendationQueryPort,
)
from app.shared.application.outbound import OutboundTelemetry


@dataclass(frozen=True)
class SendOutcome:
    """Provider-neutral value result for synthetic graph send outcomes.

    The proactive turn constructs synthetic outcomes for non-send paths (the agent
    decided not to send, safety blocked, generation threw). The optional delivery
    metadata also lets the reactive runner represent a missing durable command
    without constructing a provider service's concrete result type.
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None
    error_class: str | None = None
    suppressed: bool = False
    telemetry: OutboundTelemetry | None = None


class OutboundMessagePort(Protocol):
    """Direct sender compatibility seam used by graph fakes and legacy adapters."""

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        quote_message_id: str | None = None,
    ) -> DeliveryResultPort: ...


@dataclass(frozen=True)
class FaqBypassResult:
    """A high-confidence FAQ answer ready to send without an LLM turn.

    The deterministic FAQ-bypass cascade returns this when it is confident;
    ``None`` means "abstain — route to the agent". ``answer`` is the only field
    the runner sends; the rest are carried for the decision log.

    ``runner_up_score`` carries the second-best match's similarity so the runner
    can abstain on low-margin hits (top only slightly better than runner-up →
    fall through to the LLM). ``None`` when only one candidate was returned.
    """

    answer: str
    faq_id: str | None = None
    tier: str = ""  # exact / hybrid
    score: float = 0.0
    reason: str = ""
    latency_ms: float = 0.0
    runner_up_score: float | None = None


@dataclass(frozen=True)
class ReplyPolicyResult:
    """Final user-visible text plus bounded observability metadata."""

    output: str
    verdict: str
    trigger: str | None = None


class ReplyPolicyPort(Protocol):
    """Finalize candidate text independently of routing and transport layers."""

    def finalize(
        self,
        candidate: str,
        *,
        generated: bool,
        user_text: str,
    ) -> ReplyPolicyResult: ...


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
        delivery_status: Any = None,
        trace_id: str | None = None,
        outcome_metadata: dict | None = None,
        decision_trace: dict | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
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
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> bool: ...

    async def dispatch_outbound_message(
        self, *, message_id: int
    ) -> DeliveryResultPort | None: ...

    async def acquire_lock(self, conv_id: Any) -> Any: ...


class LeadContextPort(LeadContextQueryPort, Protocol):
    """Lead-profile context the brain injects into the agent prompt.

    ``context`` does one DB fetch and returns both the profile text and the
    next lead-collection question (``""`` each on miss); ``profile_text`` is the
    single-fetch flavor used by the proactive turn. ``instruction`` is a pure
    prompt-assembly post-processor. The agent is the single owner of contact
    questions — there is no post-reply CTA append.
    """

    pass


class RuntimePolicyPort(Protocol):
    """Resolve only an active, validated installation into immutable turn policy."""

    async def resolve_active_policy(self) -> Any: ...

    async def runtime_stamp_is_current(
        self, *, revision_id: str, authority_generation: int, runtime_fingerprint: str
    ) -> bool: ...


class RetrievalPort(
    ProjectKnowledgeQueryPort,
    PersonaBodyResolver,
    RecommendationQueryPort,
    Protocol,
):
    """Compatibility aggregate while Phase 5/6 split conversation and recruitment reads."""

    async def match_memories(
        self, embedding: str, top_k: int, filters_json: str
    ) -> list[Any]: ...


class FaqBypassPort(Protocol):
    """Deterministic, non-LLM FAQ short-circuit that runs before the agent node.

    Returns a ready-to-send :class:`FaqBypassResult` on a high-confidence hit, or
    ``None`` to abstain (the agent then handles the turn as usual). Backed by
    :class:`app.graph.factories._FaqBypassAdapter`; ``None`` in graph unit tests.
    """

    async def try_answer(self, user_text: str) -> FaqBypassResult | None: ...


class DirectContextPort(Protocol):
    async def resolve(self, conversation: Any, user_text: str) -> Any: ...


__all__ = [
    "SendOutcome",
    "DeliveryResultPort",
    "OutboundMessagePort",
    "FaqBypassResult",
    "ReplyPolicyResult",
    "ReplyPolicyPort",
    "FaqBypassPort",
    "ConversationPort",
    "ConversationStatePort",
    "LeadContextPort",
    "DirectContextPort",
    "RetrievalPort",
]
